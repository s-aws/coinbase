"""Slice 2R12 eligibility primitives with no attempt authority.

The objects in this module are intentionally separate from the one-use Preview
attempt.  An eligibility cycle is durably counted before any Coinbase read,
exposes only the six authorized read categories, and cannot issue Preview or an
exchange mutation.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import errno
import fcntl
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import stat
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping
from uuid import UUID

from application.admin_api.futures_order_preview import (
    FUTURES_PREVIEW_ACTOR_ID,
    FUTURES_PREVIEW_ARTIFACT_ROOT,
    FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS,
    FUTURES_PREVIEW_PRODUCT_ID,
    FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING,
    FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING,
    FUTURES_PREVIEW_R11_ARTIFACT_PATH,
    FUTURES_PREVIEW_R11_DEVICE,
    FUTURES_PREVIEW_R11_EVIDENCE_SHA256,
    FUTURES_PREVIEW_R11_FILE_SHA256,
    FUTURES_PREVIEW_R11_INODE,
    FUTURES_PREVIEW_R11_MODE,
    FUTURES_PREVIEW_R11_MTIME_NS,
    FUTURES_PREVIEW_R11_NLINK,
    FUTURES_PREVIEW_R11_SIZE,
    FUTURES_PREVIEW_R10_ARTIFACT_PATH,
    FUTURES_PREVIEW_R10_DEVICE,
    FUTURES_PREVIEW_R10_FILE_SHA256,
    FUTURES_PREVIEW_R10_INODE,
    FUTURES_PREVIEW_R10_MODE,
    FUTURES_PREVIEW_R10_MTIME_NS,
    FUTURES_PREVIEW_R10_SIZE,
    FUTURES_PREVIEW_R9_ARTIFACT_PATH,
    FUTURES_PREVIEW_R9_DEVICE,
    FUTURES_PREVIEW_R9_FILE_SHA256,
    FUTURES_PREVIEW_R9_INODE,
    FUTURES_PREVIEW_R9_MODE,
    FUTURES_PREVIEW_R9_MTIME_NS,
    FUTURES_PREVIEW_R9_SIZE,
    FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING,
    FUTURES_PREVIEW_R8_ARTIFACT_PATH,
    FUTURES_PREVIEW_R8_DEVICE,
    FUTURES_PREVIEW_R8_INODE,
    FUTURES_PREVIEW_R8_MODE,
    FUTURES_PREVIEW_R8_MTIME_NS,
    FUTURES_PREVIEW_R8_SIZE,
    FUTURES_PREVIEW_ROLE,
    FuturesOrderPreviewArtifactStore,
    _R11_CONSUMED_PREVIEW_IDENTIFIER_SHA256,
    _SDK_MARGIN_SETTING_FIELDS,
    _validate_opaque_preview_artifact,
    _validate_opaque_preview_artifact_metadata_only,
    _classify_slice2_preview_margin_windows_policy,
    _decimal,
    _decimal_text,
    _fsync_directory,
    _futures_preview_r8_advisory_lock,
    _mapping,
    _plain,
    _preview_request,
    _sanitized_market_evidence,
    _sanitized_position_evidence,
    _sanitized_product_evidence,
    _timestamp,
    _usd_money_value,
    _write_all,
    build_futures_order_preview_candidate,
    canonical_json,
    canonical_sha256,
    validate_post_r10_preview_response_acceptance,
    validate_production_futures_order_preview_r7_opaque_chain,
    validate_preview_against_candidate,
)
from application.admin_api.futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)


FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS = MappingProxyType(
    {
        "get_futures_balance_summary": 1,
        "get_intraday_margin_setting": 1,
        "get_current_margin_window": 2,
    }
)
_R12_EXACT_INTRADAY_MARGIN_SETTING = "INTRADAY_MARGIN_SETTING_INTRADAY"
_R12_EXACT_FCM_MARGIN_WINDOW_TYPE = "FCM_MARGIN_WINDOW_TYPE_INTRADAY"
FUTURES_PREVIEW_R12_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r12"
)
_PRODUCTION_FUTURES_PREVIEW_R12_ARTIFACT_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r12.jsonl"
)
_PRODUCTION_FUTURES_PREVIEW_R12_ELIGIBILITY_PATH = (
    FUTURES_PREVIEW_ARTIFACT_ROOT
    / "futures_exact_no_live_preview_slice_2r12_eligibility.jsonl"
)
FUTURES_PREVIEW_R12_ARTIFACT_PATH = (
    _PRODUCTION_FUTURES_PREVIEW_R12_ARTIFACT_PATH
)
FUTURES_PREVIEW_R12_ELIGIBILITY_PATH = (
    _PRODUCTION_FUTURES_PREVIEW_R12_ELIGIBILITY_PATH
)
FUTURES_PREVIEW_R12_ELIGIBILITY_MAX_TRANSITION_AGE_SECONDS = 10
FUTURES_PREVIEW_R12_ELIGIBILITY_MAX_CYCLE_AGE_SECONDS = 300
FUTURES_PREVIEW_R12_SDK_DISTRIBUTION = "coinbase-advanced-py"
FUTURES_PREVIEW_R12_SDK_VERSION = "1.8.4"
FUTURES_PREVIEW_R12_API_BASE_URL = "api.coinbase.com"
FUTURES_PREVIEW_R12_HTTP_TIMEOUT_SECONDS = 30
FUTURES_PREVIEW_R12_CA_BUNDLE = (
    "/usr/local/lib/python3.13/site-packages/certifi/cacert.pem"
)
FUTURES_PREVIEW_R12_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r11.jsonl",
    "file_sha256": FUTURES_PREVIEW_R11_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R11_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R11_DEVICE),
    "inode": str(FUTURES_PREVIEW_R11_INODE),
    "size_bytes": FUTURES_PREVIEW_R11_SIZE,
    "mode": f"{FUTURES_PREVIEW_R11_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R11_MTIME_NS),
    "nlink": FUTURES_PREVIEW_R11_NLINK,
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "chain_validation": {
        "r1_through_r7": "opaque_hash_and_metadata",
        "r8": "metadata_only_content_and_hash_inaccessible",
        "r9_through_r11": "opaque_hash_and_metadata",
    },
}

_ELIGIBILITY_CATEGORIES = (
    "api_key_permissions",
    "portfolio_catalog",
    "product",
    "best_bid_ask",
    "futures_positions",
    "futures_margin_collateral",
)
_ELIGIBILITY_CALL_LIMITS = MappingProxyType(
    {category: 1 for category in _ELIGIBILITY_CATEGORIES}
)
_SCHEMA_VERSION = "1"
_MAX_CYCLES = 10
_MAX_LEDGER_BYTES = 256 * 1024
_MAX_LEDGER_RECORDS = (_MAX_CYCLES * 2) + 1
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_COMPLETION_CLASSIFICATIONS = frozenset(
    {
        "exact_v3_eligible",
        "permission_or_portfolio_ineligible",
        "product_contract_ineligible",
        "market_book_ineligible",
        "position_exposure_ineligible",
        "candidate_caps_ineligible",
        "margin_collateral_ineligible",
        "read_outcome_unknown",
        "internal_validation_blocked",
    }
)
_PERSISTED_COMPLETION_CLASSIFICATIONS = _COMPLETION_CLASSIFICATIONS | {
    "product_or_market_or_position_ineligible"
}
_CANDIDATE_FAILURE_CLASSIFICATIONS = MappingProxyType(
    {
        "futures_preview_product_identity_blocked": (
            "product_contract_ineligible"
        ),
        "futures_preview_avp_display_name_blocked": (
            "product_contract_ineligible"
        ),
        "futures_preview_product_type_blocked": "product_contract_ineligible",
        "futures_preview_product_status_blocked": (
            "product_contract_ineligible"
        ),
        "futures_preview_product_trading_blocked": (
            "product_contract_ineligible"
        ),
        "futures_preview_avp_perp_style_identity_blocked": (
            "product_contract_ineligible"
        ),
        "futures_preview_contract_size_invalid": "product_contract_ineligible",
        "futures_preview_avp_contract_size_blocked": (
            "product_contract_ineligible"
        ),
        "futures_preview_product_price_invalid": "product_contract_ineligible",
        "futures_preview_price_increment_invalid": (
            "product_contract_ineligible"
        ),
        "futures_preview_base_increment_invalid": (
            "product_contract_ineligible"
        ),
        "futures_preview_base_min_size_invalid": (
            "product_contract_ineligible"
        ),
        "futures_preview_one_contract_rule_blocked": (
            "product_contract_ineligible"
        ),
        "futures_preview_pricebook_missing": "market_book_ineligible",
        "futures_preview_pricebook_ambiguous": "market_book_ineligible",
        "futures_preview_market_time_missing": "market_book_ineligible",
        "futures_preview_market_time_invalid": "market_book_ineligible",
        "futures_preview_market_time_unzoned": "market_book_ineligible",
        "futures_preview_market_stale": "market_book_ineligible",
        "futures_preview_bids_missing": "market_book_ineligible",
        "futures_preview_asks_missing": "market_book_ineligible",
        "futures_preview_bids_price_invalid": "market_book_ineligible",
        "futures_preview_asks_price_invalid": "market_book_ineligible",
        "futures_preview_crossed_or_ambiguous_book": (
            "market_book_ineligible"
        ),
        "futures_preview_best_bid_tick_misaligned": "market_book_ineligible",
        "futures_preview_limit_tick_blocked": "market_book_ineligible",
        "futures_preview_positions_ambiguous": "position_exposure_ineligible",
        "futures_preview_position_contracts_invalid": (
            "position_exposure_ineligible"
        ),
        "futures_preview_existing_product_exposure_blocked": (
            "position_exposure_ineligible"
        ),
        "futures_preview_opening_cap_blocked": "candidate_caps_ineligible",
        "futures_preview_exposure_cap_blocked": "candidate_caps_ineligible",
        "futures_preview_buffered_close_cap_blocked": (
            "candidate_caps_ineligible"
        ),
        "futures_preview_turnover_cap_blocked": "candidate_caps_ineligible",
    }
)


class FuturesPreviewR12EligibilityError(ValueError):
    """Fixed, value-blind failure at the R12 non-attempt boundary."""


def _candidate_failure_classification(error: BaseException) -> str:
    """Map only exact internal reason constants to value-blind boundaries."""

    if type(error) is not ValueError or len(error.args) != 1:
        return "internal_validation_blocked"
    reason = error.args[0]
    if type(reason) is not str:
        return "internal_validation_blocked"
    return _CANDIDATE_FAILURE_CLASSIFICATIONS.get(
        reason,
        "internal_validation_blocked",
    )


_R12_CLAIM_STAGING_MAX_BYTES = 256 * 1024


class FuturesPreviewR12ArtifactStore(FuturesOrderPreviewArtifactStore):
    """R12-only atomic claim-to-terminal artifact transition."""

    def reserve(self, claim: Mapping[str, Any]) -> str:
        if claim.get("artifact_type") != FUTURES_PREVIEW_R12_ARTIFACT_TYPE:
            raise FuturesPreviewR12EligibilityError(
                "R12 artifact claim type is invalid"
            )
        with _futures_preview_r8_advisory_lock(
            FUTURES_PREVIEW_R8_ARTIFACT_PATH,
            exclusive=True,
            nonblocking=self.reservation_lock_nonblocking,
        ):
            self._normalize_atomic_claim_publication_unlocked()
            return self._reserve_atomic_unlocked(claim)

    def normalize_atomic_claim_publication(self) -> None:
        """Normalize only R12-owned staging state before recovery reads."""

        with _futures_preview_r8_advisory_lock(
            FUTURES_PREVIEW_R8_ARTIFACT_PATH,
            exclusive=True,
            nonblocking=self.reservation_lock_nonblocking,
        ):
            self._normalize_atomic_claim_publication_unlocked()

    def _reserve_atomic_unlocked(self, claim: Mapping[str, Any]) -> str:
        """Publish one complete claim with an atomic no-clobber link."""

        self._prepare_parent()  # noqa: SLF001
        try:
            current = self.path.lstat()
        except FileNotFoundError:
            current = None
        except OSError:
            raise FuturesPreviewR12EligibilityError(
                "R12 claim persistence state is invalid"
            ) from None
        if current is not None:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt is already claimed"
            )

        wrapped = self._record("claim", claim)  # noqa: SLF001
        payload = (canonical_json(wrapped) + "\n").encode("utf-8")
        if len(payload) > _R12_CLAIM_STAGING_MAX_BYTES:
            raise FuturesPreviewR12EligibilityError(
                "R12 claim persistence blocked before claim"
            )

        descriptor = -1
        temporary_path: Path | None = None
        staged_identity: tuple[int, int] | None = None
        published = False
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=self._claim_staging_prefix(),
                dir=os.fspath(self.path.parent),
            )
            temporary_path = Path(temporary_name)
            opened = os.fstat(descriptor)
            staged_identity = (opened.st_dev, opened.st_ino)
            if not (
                stat.S_ISREG(opened.st_mode)
                and opened.st_uid == os.getuid()
                and stat.S_IMODE(opened.st_mode) == 0o600
                and opened.st_nlink == 1
                and opened.st_size == 0
            ):
                raise OSError("unsafe R12 claim staging file")
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            sealed = os.fstat(descriptor)
            if not (
                (sealed.st_dev, sealed.st_ino) == staged_identity
                and sealed.st_size == len(payload)
                and stat.S_IMODE(sealed.st_mode) == 0o600
                and sealed.st_uid == os.getuid()
                and sealed.st_nlink == 1
            ):
                raise OSError("R12 claim staging file is invalid")
            os.close(descriptor)
            descriptor = -1

            os.link(
                temporary_path,
                self.path,
                follow_symlinks=False,
            )
            published = True
            _fsync_directory(self.path.parent)
            os.unlink(temporary_path)
            temporary_path = None
            _fsync_directory(self.path.parent)

            canonical = self._safe_regular_lstat()  # noqa: SLF001
            if not (
                (canonical.st_dev, canonical.st_ino) == staged_identity
                and canonical.st_size == len(payload)
                and stat.S_IMODE(canonical.st_mode) == 0o600
                and canonical.st_uid == os.getuid()
                and canonical.st_nlink == 1
            ):
                raise OSError("R12 published claim is invalid")
            if self._read_rows() != [wrapped]:  # noqa: SLF001
                raise OSError("R12 published claim readback changed")
            return str(wrapped["record_sha256"])
        except Exception:
            if published:
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim persistence outcome unknown; attempt consumed"
                ) from None
            raise FuturesPreviewR12EligibilityError(
                "R12 claim persistence blocked before claim"
            ) from None
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if (
                not published
                and temporary_path is not None
                and staged_identity is not None
            ):
                try:
                    staged = temporary_path.lstat()
                    if (
                        stat.S_ISREG(staged.st_mode)
                        and staged.st_uid == os.getuid()
                        and (staged.st_dev, staged.st_ino) == staged_identity
                    ):
                        os.unlink(temporary_path)
                except OSError:
                    pass

    def _normalize_atomic_claim_publication_unlocked(self) -> None:
        """Remove safe unpublished or same-inode R12 staging links."""

        self._prepare_parent()  # noqa: SLF001
        try:
            canonical = self.path.lstat()
        except FileNotFoundError:
            canonical = None
        except OSError:
            raise FuturesPreviewR12EligibilityError(
                "R12 claim staging state is invalid"
            ) from None
        if canonical is not None and not self._safe_claim_path_metadata(
            canonical
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 claim staging state is invalid"
            )

        claim_prefix = self._claim_staging_prefix()
        terminal_prefix = self._terminal_staging_prefix()
        try:
            candidates = tuple(self.path.parent.iterdir())
        except OSError:
            raise FuturesPreviewR12EligibilityError(
                "R12 claim staging state is invalid"
            ) from None
        removed = False
        for candidate in candidates:
            is_claim_staging = candidate.name.startswith(claim_prefix)
            is_terminal_staging = candidate.name.startswith(
                terminal_prefix
            )
            if not is_claim_staging and not is_terminal_staging:
                continue
            try:
                staged = candidate.lstat()
            except OSError:
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim staging state is invalid"
                ) from None
            allowed_modes = (
                {0o600}
                if is_claim_staging
                else {0o400, 0o600}
            )
            if not (
                stat.S_ISREG(staged.st_mode)
                and staged.st_uid == os.getuid()
                and stat.S_IMODE(staged.st_mode) in allowed_modes
                and 0 <= staged.st_size <= _R12_CLAIM_STAGING_MAX_BYTES
                and staged.st_nlink >= 1
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim staging state is invalid"
                )
            same_as_canonical = bool(
                canonical is not None
                and (staged.st_dev, staged.st_ino)
                == (canonical.st_dev, canonical.st_ino)
            )
            if is_terminal_staging:
                if staged.st_nlink != 1 or same_as_canonical:
                    raise FuturesPreviewR12EligibilityError(
                        "R12 claim staging state is invalid"
                    )
            elif same_as_canonical:
                if staged.st_nlink < 2:
                    raise FuturesPreviewR12EligibilityError(
                        "R12 claim staging state is invalid"
                    )
            elif staged.st_nlink != 1:
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim staging state is invalid"
                )
            try:
                os.unlink(candidate)
            except OSError:
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim staging state is invalid"
                ) from None
            removed = True

        if removed:
            try:
                _fsync_directory(self.path.parent)
            except Exception:
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim staging state is invalid"
                ) from None
        if canonical is not None:
            try:
                refreshed = self.path.lstat()
            except OSError:
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim staging state is invalid"
                ) from None
            if not (
                (refreshed.st_dev, refreshed.st_ino)
                == (canonical.st_dev, canonical.st_ino)
                and self._safe_claim_path_metadata(refreshed)
                and refreshed.st_nlink == 1
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim staging state is invalid"
                )

    @staticmethod
    def _safe_claim_path_metadata(value: os.stat_result) -> bool:
        return bool(
            stat.S_ISREG(value.st_mode)
            and value.st_uid == os.getuid()
            and stat.S_IMODE(value.st_mode) in {0o400, 0o600}
            and 0 < value.st_size <= _R12_CLAIM_STAGING_MAX_BYTES
            and value.st_nlink >= 1
        )

    def _claim_staging_prefix(self) -> str:
        return f".{self.path.name}.claim-"

    def _terminal_staging_prefix(self) -> str:
        return f".{self.path.name}.terminal-"

    def append_validated_terminal(self, result: Mapping[str, Any]) -> str:
        """Strictly validate, then atomically replace claim with terminal."""

        from application.admin_api.models import (
            AdminFuturesOrderPreviewR12Response,
        )

        terminal = deepcopy(dict(result))
        try:
            AdminFuturesOrderPreviewR12Response.model_validate(terminal)
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 terminal validation failed before persistence"
            ) from None

        try:
            rows = self._read_rows()  # noqa: SLF001
            before = self._safe_regular_lstat()  # noqa: SLF001
            claim = rows[0].get("record") if len(rows) == 1 else None
            if (
                len(rows) != 1
                or rows[0].get("record_type") != "claim"
                or not isinstance(claim, Mapping)
                or claim.get("artifact_type")
                != FUTURES_PREVIEW_R12_ARTIFACT_TYPE
                or terminal.get("claim_sha256")
                != rows[0].get("record_sha256")
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid != os.getuid()
                or before.st_nlink != 1
            ):
                raise ValueError("claim state invalid")
            wrapped = self._record(  # noqa: SLF001
                "result",
                terminal,
                previous_record_sha256=str(rows[0]["record_sha256"]),
            )
            wrapped["outcome"] = str(terminal["outcome"])
            wrapped["record_sha256"] = canonical_sha256(
                {
                    key: value
                    for key, value in wrapped.items()
                    if key != "record_sha256"
                }
            )
            payload = (
                canonical_json(rows[0])
                + "\n"
                + canonical_json(wrapped)
                + "\n"
            ).encode("utf-8")
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 terminal persistence state is invalid"
            ) from None

        self._prepare_parent()  # noqa: SLF001
        descriptor = -1
        temporary_path: Path | None = None
        replaced = False
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=self._terminal_staging_prefix(),
                dir=os.fspath(self.path.parent),
            )
            temporary_path = Path(temporary_name)
            opened = os.fstat(descriptor)
            if not (
                stat.S_ISREG(opened.st_mode)
                and opened.st_uid == os.getuid()
                and stat.S_IMODE(opened.st_mode) == 0o600
                and opened.st_nlink == 1
            ):
                raise OSError("unsafe terminal temporary file")
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            sealed = os.fstat(descriptor)
            if (
                sealed.st_size != len(payload)
                or stat.S_IMODE(sealed.st_mode) != 0o400
            ):
                raise OSError("terminal temporary file not sealed")
            os.close(descriptor)
            descriptor = -1

            current = self._safe_regular_lstat()  # noqa: SLF001
            if (
                (current.st_dev, current.st_ino, current.st_size)
                != (before.st_dev, before.st_ino, before.st_size)
                or stat.S_IMODE(current.st_mode) != 0o600
                or current.st_uid != os.getuid()
                or current.st_nlink != 1
            ):
                raise OSError("R12 claim identity changed")
            os.replace(temporary_path, self.path)
            replaced = True
            _fsync_directory(self.path.parent)
            observed = self.read_completed()
            if observed != terminal:
                raise OSError("R12 terminal readback changed")
            return str(wrapped["record_sha256"])
        except BaseException:
            if replaced:
                try:
                    if self.read_completed() == terminal:
                        return str(wrapped["record_sha256"])
                except Exception:
                    pass
            raise FuturesPreviewR12EligibilityError(
                "R12 terminal persistence unavailable; attempt consumed"
            ) from None
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if not replaced and temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


def _exact_int_counters(
    value: Any,
    expected: Mapping[str, int],
) -> bool:
    return bool(
        isinstance(value, dict)
        and set(value) == set(expected)
        and all(
            type(value.get(key)) is int
            and value.get(key) == expected[key]
            for key in expected
        )
    )


def validate_r12_zero_retry_redirect_transport(
    delegate: Any,
) -> dict[str, Any]:
    """Prove the pinned SDK transport cannot retry, redirect, or proxy."""

    try:
        if version(FUTURES_PREVIEW_R12_SDK_DISTRIBUTION) != (
            FUTURES_PREVIEW_R12_SDK_VERSION
        ):
            raise ValueError("SDK version drift")
        getter = getattr(delegate, "get_sdk_client", None)
        if not callable(getter):
            raise ValueError("SDK client unavailable")
        sdk_client = getter()
        session = getattr(sdk_client, "session", None)
        adapters = getattr(session, "adapters", None)
        if (
            getattr(sdk_client, "base_url", None)
            != FUTURES_PREVIEW_R12_API_BASE_URL
            or type(getattr(sdk_client, "timeout", None)) is not int
            or sdk_client.timeout != FUTURES_PREVIEW_R12_HTTP_TIMEOUT_SECONDS
            or getattr(sdk_client, "rate_limit_headers", None) is not False
            or not isinstance(adapters, dict)
            or set(adapters) != {"http://", "https://"}
            or getattr(session, "trust_env", None) is not False
            or getattr(session, "verify", None)
            != FUTURES_PREVIEW_R12_CA_BUNDLE
            or getattr(session, "proxies", None) != {}
            or type(getattr(session, "max_redirects", None)) is not int
            or session.max_redirects != 0
        ):
            raise ValueError("transport policy drift")
        retry_totals: dict[str, int] = {}
        for scheme, adapter in adapters.items():
            retry_total = getattr(
                getattr(adapter, "max_retries", None),
                "total",
                None,
            )
            if type(retry_total) is not int or retry_total != 0:
                raise ValueError("retry policy drift")
            retry_totals[scheme] = retry_total
    except Exception:
        raise FuturesPreviewR12EligibilityError(
            "R12 zero-retry zero-redirect transport is invalid"
        ) from None
    return {
        "schema_version": "1",
        "source": "backend_coinbase_sdk_transport",
        "sdk_distribution": FUTURES_PREVIEW_R12_SDK_DISTRIBUTION,
        "sdk_version": FUTURES_PREVIEW_R12_SDK_VERSION,
        "api_base_url": FUTURES_PREVIEW_R12_API_BASE_URL,
        "timeout_seconds": FUTURES_PREVIEW_R12_HTTP_TIMEOUT_SECONDS,
        "adapter_schemes": ["http://", "https://"],
        "adapter_retry_total": retry_totals,
        "redirect_max": 0,
        "trust_env": False,
        "proxies_configured": False,
        "ca_bundle_pinned": True,
        "rate_limit_headers": False,
        "validated": True,
    }


def _valid_r12_transport_policy_evidence(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    evidence = dict(value)
    return bool(
        set(evidence)
        == {
            "schema_version",
            "source",
            "sdk_distribution",
            "sdk_version",
            "api_base_url",
            "timeout_seconds",
            "adapter_schemes",
            "adapter_retry_total",
            "redirect_max",
            "trust_env",
            "proxies_configured",
            "ca_bundle_pinned",
            "rate_limit_headers",
            "validated",
        }
        and evidence.get("schema_version") == "1"
        and evidence.get("source") == "backend_coinbase_sdk_transport"
        and evidence.get("sdk_distribution")
        == FUTURES_PREVIEW_R12_SDK_DISTRIBUTION
        and evidence.get("sdk_version") == FUTURES_PREVIEW_R12_SDK_VERSION
        and evidence.get("api_base_url") == FUTURES_PREVIEW_R12_API_BASE_URL
        and type(evidence.get("timeout_seconds")) is int
        and evidence.get("timeout_seconds")
        == FUTURES_PREVIEW_R12_HTTP_TIMEOUT_SECONDS
        and evidence.get("adapter_schemes") == ["http://", "https://"]
        and _exact_int_counters(
            evidence.get("adapter_retry_total"),
            {"http://": 0, "https://": 0},
        )
        and type(evidence.get("redirect_max")) is int
        and evidence.get("redirect_max") == 0
        and evidence.get("trust_env") is False
        and evidence.get("proxies_configured") is False
        and evidence.get("ca_bundle_pinned") is True
        and evidence.get("rate_limit_headers") is False
        and evidence.get("validated") is True
    )


def validate_production_futures_order_preview_r12_predecessor(
) -> dict[str, Any]:
    """Bind R1-R11 while keeping the restricted predecessor metadata-only."""

    validate_production_futures_order_preview_r7_opaque_chain()
    _validate_opaque_preview_artifact_metadata_only(
        FUTURES_PREVIEW_R8_ARTIFACT_PATH,
        expected_device=FUTURES_PREVIEW_R8_DEVICE,
        expected_inode=FUTURES_PREVIEW_R8_INODE,
        expected_size=FUTURES_PREVIEW_R8_SIZE,
        expected_mode=FUTURES_PREVIEW_R8_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R8_MTIME_NS,
    )
    for values in (
        (
            FUTURES_PREVIEW_R9_ARTIFACT_PATH,
            FUTURES_PREVIEW_R9_FILE_SHA256,
            FUTURES_PREVIEW_R9_DEVICE,
            FUTURES_PREVIEW_R9_INODE,
            FUTURES_PREVIEW_R9_SIZE,
            FUTURES_PREVIEW_R9_MODE,
            FUTURES_PREVIEW_R9_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R10_ARTIFACT_PATH,
            FUTURES_PREVIEW_R10_FILE_SHA256,
            FUTURES_PREVIEW_R10_DEVICE,
            FUTURES_PREVIEW_R10_INODE,
            FUTURES_PREVIEW_R10_SIZE,
            FUTURES_PREVIEW_R10_MODE,
            FUTURES_PREVIEW_R10_MTIME_NS,
        ),
        (
            FUTURES_PREVIEW_R11_ARTIFACT_PATH,
            FUTURES_PREVIEW_R11_FILE_SHA256,
            FUTURES_PREVIEW_R11_DEVICE,
            FUTURES_PREVIEW_R11_INODE,
            FUTURES_PREVIEW_R11_SIZE,
            FUTURES_PREVIEW_R11_MODE,
            FUTURES_PREVIEW_R11_MTIME_NS,
        ),
    ):
        (
            artifact_path,
            file_sha256,
            device,
            inode,
            size,
            mode,
            mtime_ns,
        ) = values
        _validate_opaque_preview_artifact(
            artifact_path,
            expected_file_sha256=file_sha256,
            expected_device=device,
            expected_inode=inode,
            expected_size=size,
            expected_mode=mode,
            expected_mtime_ns=mtime_ns,
        )
    return deepcopy(FUTURES_PREVIEW_R12_PREDECESSOR_BINDING)


def validate_r12_margin_collateral_evidence(value: Any) -> Decimal:
    """Return available US CFM margin for the exact V3 pair without sweeps."""

    evidence = _mapping(value)
    if (
        evidence.get("status") != "ready"
        or evidence.get("account_family") != "coinbase_futures_us_cfm"
        or evidence.get("source") != "backend_rest_client"
        or evidence.get("intx_applicability")
        != "not_applicable_us_account"
        or not isinstance(evidence.get("errors"), list)
        or bool(evidence["errors"])
    ):
        raise ValueError("futures_preview_margin_collateral_ambiguous")
    if "futures_sweeps" in evidence:
        raise ValueError("futures_preview_margin_sweeps_not_authorized")
    if not _exact_int_counters(
        evidence.get("source_read_attempts"),
        FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS,
    ):
        raise ValueError("futures_preview_margin_source_reads_ambiguous")

    summary = _mapping(evidence.get("balance_summary"))
    available = _usd_money_value(
        summary.get("available_margin"),
        "available_margin",
    )
    _usd_money_value(summary.get("total_usd_balance"), "total_usd_balance")
    _usd_money_value(summary.get("cfm_usd_balance"), "cfm_usd_balance")
    _usd_money_value(
        summary.get("futures_buying_power"),
        "futures_buying_power",
    )
    _usd_money_value(summary.get("initial_margin"), "initial_margin")
    _usd_money_value(
        summary.get("liquidation_threshold"),
        "liquidation_threshold",
    )
    measure = _mapping(summary.get("intraday_margin_window_measure"))
    if (
        measure.get("margin_window_type")
        != _R12_EXACT_FCM_MARGIN_WINDOW_TYPE
    ):
        raise ValueError("futures_preview_margin_window_measure_ambiguous")
    for field in ("maintenance_margin", "liquidation_buffer"):
        amount = _decimal(measure.get(field), field)
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"futures_preview_margin_{field}_invalid")

    setting_evidence = _mapping(evidence.get("intraday_margin_setting"))
    setting = setting_evidence.get("setting")
    if (
        not isinstance(setting, str)
        or setting not in FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS
        or bool(set(setting_evidence) - _SDK_MARGIN_SETTING_FIELDS)
    ):
        raise ValueError("futures_preview_margin_setting_ambiguous")
    if setting != _R12_EXACT_INTRADAY_MARGIN_SETTING:
        raise ValueError("futures_preview_margin_setting_not_exact_v3")

    margin_windows_diagnostic = _classify_slice2_preview_margin_windows_policy(
        evidence,
        policy_version="v3",
    )
    if (
        not margin_windows_diagnostic["margin_window_policy_satisfied"]
        or margin_windows_diagnostic["classification"] != "ready"
    ):
        raise ValueError("futures_preview_margin_windows_ambiguous")
    windows = evidence.get("current_margin_windows")
    if not isinstance(windows, list):
        raise ValueError("futures_preview_margin_windows_ambiguous")
    for item in windows:
        window = _mapping(item)
        for killswitch_field in (
            "is_intraday_margin_killswitch_enabled",
            "is_intraday_margin_enrollment_killswitch_enabled",
        ):
            killswitch = window.get(killswitch_field)
            if not isinstance(killswitch, bool):
                raise ValueError("futures_preview_margin_killswitch_ambiguous")
            if killswitch:
                raise ValueError("futures_preview_margin_killswitch_enabled")
    if available <= 0:
        raise ValueError("futures_preview_available_margin_not_positive")
    return available


_R12_COMPLETION_MINT_TOKEN = object()


class _R12EligibilityCompletionCapability:
    """One-use proof minted only after all six facade reads ran once."""

    __slots__ = (
        "_cycle_number",
        "_nonce",
        "_start_sha256",
        "_store",
        "_used",
    )

    def __init__(
        self,
        *,
        store: FuturesPreviewR12EligibilityStore,
        nonce: object,
        cycle_number: int,
        start_sha256: str,
        _mint_token: object,
    ) -> None:
        if _mint_token is not _R12_COMPLETION_MINT_TOKEN:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility completion capability is invalid"
            )
        self._store = store
        self._nonce = nonce
        self._cycle_number = cycle_number
        self._start_sha256 = start_sha256
        self._used = False

    def consume(self, *, cycle_number: int) -> None:
        if (
            self._used
            or cycle_number != self._cycle_number
            or not self._store._cycle_capability_is_active(  # noqa: SLF001
                nonce=self._nonce,
                cycle_number=self._cycle_number,
                start_sha256=self._start_sha256,
            )
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility completion capability is invalid"
            )
        self._used = True


class _R12EligibilityCycleCapability:
    """One-use proof that a cycle is started under the active file lease."""

    __slots__ = (
        "_completion_minted",
        "_cycle_number",
        "_nonce",
        "_start_sha256",
        "_store",
        "_used",
    )

    def __init__(
        self,
        *,
        store: FuturesPreviewR12EligibilityStore,
        nonce: object,
        cycle_number: int,
        start_sha256: str,
    ) -> None:
        self._store = store
        self._nonce = nonce
        self._cycle_number = cycle_number
        self._start_sha256 = start_sha256
        self._used = False
        self._completion_minted = False

    def consume(self) -> None:
        if self._used or not self._store._cycle_capability_is_active(  # noqa: SLF001
            nonce=self._nonce,
            cycle_number=self._cycle_number,
            start_sha256=self._start_sha256,
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility cycle capability is invalid"
            )
        self._used = True

    def mint_completion(
        self,
        *,
        call_attempts: Mapping[str, int],
    ) -> _R12EligibilityCompletionCapability:
        if (
            not self._used
            or self._completion_minted
            or dict(call_attempts)
            != {category: 1 for category in _ELIGIBILITY_CATEGORIES}
            or any(
                type(call_attempts.get(category)) is not int
                for category in _ELIGIBILITY_CATEGORIES
            )
            or not self._store._cycle_capability_is_active(  # noqa: SLF001
                nonce=self._nonce,
                cycle_number=self._cycle_number,
                start_sha256=self._start_sha256,
            )
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility completion capability is invalid"
            )
        self._completion_minted = True
        return _R12EligibilityCompletionCapability(
            store=self._store,
            nonce=self._nonce,
            cycle_number=self._cycle_number,
            start_sha256=self._start_sha256,
            _mint_token=_R12_COMPLETION_MINT_TOKEN,
        )


class _R12EligibilityTransitionCapability:
    """One-use lease proof for the eligible-to-claim transition."""

    __slots__ = (
        "_completion_sha256",
        "_cycle_number",
        "_attempt_artifact_path",
        "_delegate",
        "_nonce",
        "_store",
        "_used",
    )

    def __init__(
        self,
        *,
        store: FuturesPreviewR12EligibilityStore,
        nonce: object,
        cycle_number: int,
        completion_sha256: str,
        attempt_artifact_path: Path,
        delegate: Any,
    ) -> None:
        self._store = store
        self._nonce = nonce
        self._cycle_number = cycle_number
        self._completion_sha256 = completion_sha256
        self._attempt_artifact_path = Path(attempt_artifact_path)
        self._delegate = delegate
        self._used = False

    @property
    def store(self) -> FuturesPreviewR12EligibilityStore:
        return self._store

    @property
    def cycle_number(self) -> int:
        return self._cycle_number

    @property
    def completion_sha256(self) -> str:
        return self._completion_sha256

    @property
    def attempt_artifact_path(self) -> Path:
        return self._attempt_artifact_path

    def active_lease_nonce(self) -> object:
        """Return the exact still-active workflow lease for terminal writes."""

        self._store.require_active_workflow_lease(self._nonce)
        return self._nonce

    def consume(self) -> Any:
        if self._used or not self._store._transition_capability_is_active(  # noqa: SLF001
            nonce=self._nonce,
            cycle_number=self._cycle_number,
            completion_sha256=self._completion_sha256,
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility transition capability is invalid"
            )
        self._used = True
        return self._delegate


class FuturesPreviewR12EligibilityClient:
    """One-cycle facade exposing only the authorized eligibility reads."""

    __slots__ = ("_capability", "_delegate", "_call_attempts")

    def __init__(
        self,
        delegate: Any,
        *,
        _capability: _R12EligibilityCycleCapability | None = None,
    ) -> None:
        if type(_capability) is not _R12EligibilityCycleCapability:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility client requires a started cycle"
            )
        _capability.consume()
        self._capability = _capability
        self._delegate = delegate
        self._call_attempts = {
            category: 0 for category in _ELIGIBILITY_CATEGORIES
        }

    @property
    def call_attempts(self) -> dict[str, int]:
        return dict(self._call_attempts)

    def _consume(self, category: str) -> None:
        if self._call_attempts[category] != 0:
            raise ValueError(f"{category} already attempted")
        self._call_attempts[category] = 1

    def completion_capability(
        self,
    ) -> _R12EligibilityCompletionCapability:
        return self._capability.mint_completion(
            call_attempts=self._call_attempts
        )

    def get_api_key_permissions(self) -> Any:
        self._consume("api_key_permissions")
        return self._delegate.get_api_key_permissions()

    def list_portfolios(self) -> Any:
        self._consume("portfolio_catalog")
        return self._delegate.get_futures_preview_eligibility_portfolios()

    def get_product_dict(self, product_id: str) -> Any:
        if product_id != FUTURES_PREVIEW_PRODUCT_ID:
            raise ValueError("R12 eligibility product scope is invalid")
        self._consume("product")
        return self._delegate.get_product_dict(product_id)

    def get_best_bid_ask(self, *, product_ids: list[str]) -> Any:
        if product_ids != [FUTURES_PREVIEW_PRODUCT_ID]:
            raise ValueError("R12 eligibility market scope is invalid")
        self._consume("best_bid_ask")
        return self._delegate.get_best_bid_ask(product_ids=product_ids)

    def get_futures_positions(self) -> Any:
        self._consume("futures_positions")
        return self._delegate.get_futures_positions()

    def get_futures_margin_collateral_snapshot(self) -> Any:
        self._consume("futures_margin_collateral")
        return (
            self._delegate
            .get_futures_preview_eligibility_margin_collateral_snapshot()
        )


class _R12AttemptClaimCapability:
    """One-use proof that the exact Preview-only R12 claim is durable."""

    __slots__ = ("_claim_sha256", "_preview_request", "_store", "_used")

    def __init__(
        self,
        *,
        store: FuturesOrderPreviewArtifactStore,
        claim_sha256: str,
        preview_request: Mapping[str, Any],
    ) -> None:
        self._store = store
        self._claim_sha256 = claim_sha256
        self._preview_request = deepcopy(dict(preview_request))
        self._used = False

    def consume(self) -> dict[str, Any]:
        if self._used:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt claim capability is invalid"
            )
        try:
            rows = self._store._read_rows()  # noqa: SLF001
            claim = rows[0].get("record") if len(rows) == 1 else None
            if (
                len(rows) != 1
                or rows[0].get("record_type") != "claim"
                or rows[0].get("record_sha256") != self._claim_sha256
                or not isinstance(claim, Mapping)
                or claim.get("artifact_type")
                != FUTURES_PREVIEW_R12_ARTIFACT_TYPE
                or claim.get("allowed_coinbase_methods") != ["preview_order"]
                or claim.get("preview_request_sha256")
                != canonical_sha256(self._preview_request)
                or claim.get("preview_order_attempt_max") != 1
                or claim.get("retry_attempt_max") != 0
                or claim.get("fallback_attempt_max") != 0
                or claim.get("create_order_attempt_max") != 0
                or claim.get("cancel_order_attempt_max") != 0
                or claim.get("close_position_attempt_max") != 0
                or claim.get("reduce_position_attempt_max") != 0
            ):
                raise ValueError("claim invalid")
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt claim capability is invalid"
            ) from None
        self._used = True
        return deepcopy(self._preview_request)


class FuturesPreviewR12AttemptClient:
    """Single-capability facade available only after durable R12 reservation."""

    __slots__ = (
        "_delegate",
        "_preview_order_attempt_count",
        "_preview_request",
    )

    def __init__(
        self,
        delegate: Any,
        *,
        _capability: _R12AttemptClaimCapability | None = None,
    ) -> None:
        if type(_capability) is not _R12AttemptClaimCapability:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt client requires a durable claim"
            )
        self._preview_request = _capability.consume()
        self._delegate = delegate
        self._preview_order_attempt_count = 0

    @property
    def preview_order_attempt_count(self) -> int:
        return self._preview_order_attempt_count

    def preview_order(self) -> Any:
        if self._preview_order_attempt_count != 0:
            raise ValueError("R12 Preview already attempted")
        self._preview_order_attempt_count = 1
        return self._delegate.preview_order(**deepcopy(self._preview_request))


class FuturesPreviewR12EligibilityStore:
    """Owner-only, append-before-read budget ledger for at most ten cycles."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._active_workflow_nonce: object | None = None

    @contextmanager
    def workflow_lease(self) -> Iterator[object]:
        """Hold the single nonblocking R12 workflow lease through transition."""

        self._prepare_parent()
        lock_path = self.path.with_name(f".{self.path.name}.workflow.lock")
        created = False
        try:
            lock_path.lstat()
        except FileNotFoundError:
            created = True
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility workflow lock is invalid"
            ) from exc
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | _NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility workflow lock is invalid"
            ) from exc
        locked = False
        installed_nonce: object | None = None
        try:
            self._validate_lock_identity(lock_path, descriptor)
            if created:
                os.fsync(descriptor)
                self._sync_parent()
            try:
                fcntl.flock(
                    descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
                locked = True
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise FuturesPreviewR12EligibilityError(
                        "R12 eligibility workflow is already active"
                    ) from None
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility workflow lock is invalid"
                ) from exc
            self._validate_lock_identity(lock_path, descriptor)
            nonce = object()
            if self._active_workflow_nonce is not None:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility workflow is already active"
                )
            self._active_workflow_nonce = nonce
            installed_nonce = nonce
            yield nonce
            self._validate_lock_identity(lock_path, descriptor)
        finally:
            if (
                installed_nonce is not None
                and self._active_workflow_nonce is installed_nonce
            ):
                self._active_workflow_nonce = None
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)

    def _cycle_capability_is_active(
        self,
        *,
        nonce: object,
        cycle_number: int,
        start_sha256: str,
    ) -> bool:
        if nonce is not self._active_workflow_nonce:
            return False
        try:
            descriptor = self._open(create=False)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH)
                records = self._read_records(descriptor)
            finally:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        except Exception:
            return False
        return any(
            record.get("record_type") == "eligibility_cycle_started"
            and record.get("cycle_number") == cycle_number
            and record.get("record_sha256") == start_sha256
            for record in records
        )

    def require_active_workflow_lease(self, nonce: object | None) -> None:
        """Fail closed unless this store instance owns the active lease."""

        if nonce is None or nonce is not self._active_workflow_nonce:
            raise FuturesPreviewR12EligibilityError(
                "R12 recovery requires an active workflow lease"
            )

    def _transition_capability_is_active(
        self,
        *,
        nonce: object,
        cycle_number: int,
        completion_sha256: str,
    ) -> bool:
        if nonce is not self._active_workflow_nonce:
            return False
        try:
            descriptor = self._open(create=False)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH)
                records = self._read_records(descriptor)
            finally:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        except Exception:
            return False
        if not records or any(
            record.get("record_type") == "r12_attempt_claimed"
            for record in records
        ):
            return False
        latest = records[-1]
        return bool(
            latest.get("record_type") == "eligibility_cycle_completed"
            and latest.get("cycle_number") == cycle_number
            and latest.get("record_sha256") == completion_sha256
            and latest.get("outcome") == "eligible"
            and latest.get("classification") == "exact_v3_eligible"
            and _exact_int_counters(
                latest.get("call_attempts"),
                _ELIGIBILITY_CALL_LIMITS,
            )
        )

    @property
    def cycle_count(self) -> int:
        try:
            self.path.lstat()
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            ) from exc
        descriptor = self._open(create=False)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            self._validate_open_identity(descriptor)
            return sum(
                record.get("record_type") == "eligibility_cycle_started"
                for record in self._read_records(descriptor)
            )
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            ) from exc
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def begin_cycle(
        self,
        *,
        correlation_id: str,
        started_at: datetime,
    ) -> dict[str, Any]:
        """Durably consume one non-attempt eligibility cycle before calls."""

        correlation = self._validate_correlation_id(correlation_id)
        timestamp = self._validate_timestamp(started_at)
        self._prepare_parent()
        descriptor = self._open(create=True)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._validate_open_identity(descriptor)
            records = self._read_records(descriptor)
            if any(
                record.get("record_type") == "r12_attempt_claimed"
                for record in records
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 attempt is already claimed"
                )
            cycle_count = sum(
                record.get("record_type") == "eligibility_cycle_started"
                for record in records
            )
            if cycle_count >= _MAX_CYCLES:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility cycles exhausted"
                )
            previous = (
                str(records[-1]["record_sha256"]) if records else None
            )
            record: dict[str, Any] = {
                "schema_version": _SCHEMA_VERSION,
                "record_type": "eligibility_cycle_started",
                "cycle_number": cycle_count + 1,
                "started_at": timestamp,
                "non_attempt_correlation_id": "withheld",
                "non_attempt_correlation_id_sha256": hashlib.sha256(
                    correlation.encode("utf-8")
                ).hexdigest(),
                "authorized_categories": list(_ELIGIBILITY_CATEGORIES),
                "category_call_limits": dict(_ELIGIBILITY_CALL_LIMITS),
                "margin_source_read_limits": dict(
                    FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS
                ),
                "r12_claim_created": False,
                "r12_idempotency_key_created": False,
                "r12_attempt_consumed": False,
                "preview_order_authorized": False,
                "exchange_mutations_authorized": False,
                "raw_response_included": False,
                "external_exception_text_included": False,
                "private_identifier_values_included": False,
                "previous_record_sha256": previous,
            }
            record["record_sha256"] = canonical_sha256(record)
            payload = (canonical_json(record) + "\n").encode("utf-8")
            if os.fstat(descriptor).st_size + len(payload) > _MAX_LEDGER_BYTES:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            os.lseek(descriptor, 0, os.SEEK_END)
            self._write_all(descriptor, payload)
            os.fsync(descriptor)
            self._validate_open_identity(descriptor)
            self._sync_parent()
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger write failed"
            ) from exc
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        return dict(record)

    def complete_cycle(
        self,
        *,
        cycle_number: int,
        completed_at: datetime,
        outcome: str,
        classification: str,
        call_attempts: Mapping[str, int],
        eligibility_evidence_sha256: str | None,
        _lease_nonce: object | None = None,
        _read_capability: _R12EligibilityCompletionCapability | None = None,
    ) -> dict[str, Any]:
        """Append one fixed sanitized terminal row for a started cycle."""

        timestamp = self._validate_timestamp(completed_at)
        if outcome not in {"eligible", "ineligible", "unknown"}:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility completion is invalid"
            )
        if classification not in _COMPLETION_CLASSIFICATIONS:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility completion is invalid"
            )
        attempts = dict(call_attempts)
        if set(attempts) != set(_ELIGIBILITY_CATEGORIES) or any(
            type(attempts[category]) is not int
            or attempts[category] not in {0, 1}
            for category in _ELIGIBILITY_CATEGORIES
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility completion is invalid"
            )
        if outcome == "eligible":
            if (
                classification != "exact_v3_eligible"
                or not self._is_sha256(eligibility_evidence_sha256)
                or attempts
                != {category: 1 for category in _ELIGIBILITY_CATEGORIES}
                or _lease_nonce is not self._active_workflow_nonce
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility completion is invalid"
                )
            if type(_read_capability) is not (
                _R12EligibilityCompletionCapability
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility completion capability is invalid"
                )
            _read_capability.consume(cycle_number=cycle_number)
        elif eligibility_evidence_sha256 is not None:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility completion is invalid"
            )

        descriptor = self._open(create=False)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._validate_open_identity(descriptor)
            records = self._read_records(descriptor)
            starts = [
                record
                for record in records
                if record.get("record_type") == "eligibility_cycle_started"
                and record.get("cycle_number") == cycle_number
            ]
            completions = [
                record
                for record in records
                if record.get("record_type") == "eligibility_cycle_completed"
                and record.get("cycle_number") == cycle_number
            ]
            if (
                len(starts) != 1
                or completions
                or any(
                    record.get("record_type") == "r12_attempt_claimed"
                    for record in records
                )
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility completion is invalid"
                )
            started_at = self._parse_persisted_timestamp(
                starts[0].get("started_at")
            )
            parsed_completed_at = self._parse_persisted_timestamp(timestamp)
            if (
                started_at is None
                or parsed_completed_at is None
                or parsed_completed_at < started_at
                or (
                    outcome == "eligible"
                    and (
                        parsed_completed_at - started_at
                    ).total_seconds()
                    > FUTURES_PREVIEW_R12_ELIGIBILITY_MAX_CYCLE_AGE_SECONDS
                )
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility completion is invalid"
                )
            previous = str(records[-1]["record_sha256"])
            record: dict[str, Any] = {
                "schema_version": _SCHEMA_VERSION,
                "record_type": "eligibility_cycle_completed",
                "cycle_number": cycle_number,
                "started_record_sha256": starts[0]["record_sha256"],
                "completed_at": timestamp,
                "outcome": outcome,
                "classification": classification,
                "call_attempts": attempts,
                "margin_source_read_limits": dict(
                    FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS
                ),
                "eligibility_evidence_sha256": eligibility_evidence_sha256,
                "r12_claim_created": False,
                "r12_idempotency_key_created": False,
                "r12_attempt_consumed": False,
                "raw_response_included": False,
                "external_exception_text_included": False,
                "private_identifier_values_included": False,
                "previous_record_sha256": previous,
            }
            record["record_sha256"] = canonical_sha256(record)
            payload = (canonical_json(record) + "\n").encode("utf-8")
            if os.fstat(descriptor).st_size + len(payload) > _MAX_LEDGER_BYTES:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            os.lseek(descriptor, 0, os.SEEK_END)
            self._write_all(descriptor, payload)
            os.fsync(descriptor)
            self._validate_open_identity(descriptor)
            self._sync_parent()
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger write failed"
            ) from exc
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        return dict(record)

    def mark_attempt_claimed(
        self,
        *,
        cycle_number: int,
        completion_record_sha256: str,
        claim_record_sha256: str,
        claimed_at: datetime,
    ) -> dict[str, Any]:
        """Close eligibility durably after the separate attempt claim exists."""

        if not (
            self._is_sha256(completion_record_sha256)
            and self._is_sha256(claim_record_sha256)
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt claim marker is invalid"
            )
        timestamp = self._validate_timestamp(claimed_at)
        descriptor = self._open(create=False)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._validate_open_identity(descriptor)
            records = self._read_records(descriptor)
            if not records or any(
                record.get("record_type") == "r12_attempt_claimed"
                for record in records
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 attempt claim marker is invalid"
                )
            completion = records[-1]
            if (
                completion.get("record_type")
                != "eligibility_cycle_completed"
                or completion.get("cycle_number") != cycle_number
                or completion.get("record_sha256")
                != completion_record_sha256
                or completion.get("outcome") != "eligible"
                or completion.get("classification") != "exact_v3_eligible"
                or not _exact_int_counters(
                    completion.get("call_attempts"),
                    _ELIGIBILITY_CALL_LIMITS,
                )
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 attempt claim marker is invalid"
                )
            record: dict[str, Any] = {
                "schema_version": _SCHEMA_VERSION,
                "record_type": "r12_attempt_claimed",
                "cycle_number": cycle_number,
                "eligibility_completion_record_sha256": (
                    completion_record_sha256
                ),
                "eligibility_evidence_sha256": completion[
                    "eligibility_evidence_sha256"
                ],
                "claim_record_sha256": claim_record_sha256,
                "claimed_at": timestamp,
                "r12_claim_created": True,
                "r12_idempotency_key_created": True,
                "r12_attempt_consumed": True,
                "additional_eligibility_reads_authorized": False,
                "additional_coinbase_calls_authorized": False,
                "raw_response_included": False,
                "external_exception_text_included": False,
                "private_identifier_values_included": False,
                "previous_record_sha256": completion_record_sha256,
            }
            record["record_sha256"] = canonical_sha256(record)
            payload = (canonical_json(record) + "\n").encode("utf-8")
            if os.fstat(descriptor).st_size + len(payload) > _MAX_LEDGER_BYTES:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            os.lseek(descriptor, 0, os.SEEK_END)
            self._write_all(descriptor, payload)
            os.fsync(descriptor)
            self._validate_open_identity(descriptor)
            self._sync_parent()
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt claim marker write failed"
            ) from exc
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        return dict(record)

    def validate_eligible_result(
        self,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind an in-memory success to its durable started/completed rows."""

        value = dict(result)
        expected_keys = {
            "status",
            "classification",
            "cycle_number",
            "non_attempt_correlation_id",
            "non_attempt_correlation_id_sha256",
            "r12_claim_created",
            "r12_idempotency_key_created",
            "r12_attempt_consumed",
            "eligibility_evidence",
            "eligibility_evidence_sha256",
            "eligibility_completion_record_sha256",
        }
        evidence = value.get("eligibility_evidence")
        evidence_sha256 = value.get("eligibility_evidence_sha256")
        if (
            set(value) != expected_keys
            or value.get("status") != "eligible"
            or value.get("classification") != "exact_v3_eligible"
            or value.get("non_attempt_correlation_id") != "withheld"
            or value.get("r12_claim_created") is not False
            or value.get("r12_idempotency_key_created") is not False
            or value.get("r12_attempt_consumed") is not False
            or not isinstance(evidence, Mapping)
            or not self._is_sha256(evidence_sha256)
            or evidence.get("eligibility_evidence_sha256") != evidence_sha256
            or canonical_sha256(
                {
                    key: item
                    for key, item in evidence.items()
                    if key != "eligibility_evidence_sha256"
                }
            )
            != evidence_sha256
            or not self._is_sha256(
                value.get("non_attempt_correlation_id_sha256")
            )
            or not self._is_sha256(
                value.get("eligibility_completion_record_sha256")
            )
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligible result is invalid"
            )
        descriptor = self._open(create=False)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            self._validate_open_identity(descriptor)
            records = self._read_records(descriptor)
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligible result is invalid"
            ) from exc
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        cycle_number = value.get("cycle_number")
        starts = [
            record
            for record in records
            if record.get("record_type") == "eligibility_cycle_started"
            and record.get("cycle_number") == cycle_number
        ]
        completions = [
            record
            for record in records
            if record.get("record_type") == "eligibility_cycle_completed"
            and record.get("cycle_number") == cycle_number
        ]
        if (
            len(starts) != 1
            or len(completions) != 1
            or records[-1] is not completions[0]
            or any(
                record.get("record_type") == "r12_attempt_claimed"
                for record in records
            )
            or starts[0].get("non_attempt_correlation_id_sha256")
            != value.get("non_attempt_correlation_id_sha256")
            or completions[0].get("record_sha256")
            != value.get("eligibility_completion_record_sha256")
            or completions[0].get("outcome") != "eligible"
            or completions[0].get("classification") != "exact_v3_eligible"
            or completions[0].get("eligibility_evidence_sha256")
            != evidence_sha256
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligible result is invalid"
            )
        return deepcopy(dict(evidence))

    def _prepare_parent(self) -> None:
        parent = Path(os.path.abspath(self.path.parent))
        for component in reversed((parent, *parent.parents)):
            try:
                metadata = component.lstat()
            except FileNotFoundError:
                try:
                    component.mkdir(mode=0o700)
                    metadata = component.lstat()
                except (OSError, ValueError) as exc:
                    raise FuturesPreviewR12EligibilityError(
                        "R12 eligibility ledger parent is invalid"
                    ) from exc
            except (OSError, ValueError) as exc:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger parent is invalid"
                ) from exc
            if not stat.S_ISDIR(metadata.st_mode):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger parent is invalid"
                )

    def _open(self, *, create: bool) -> int:
        flags = os.O_RDWR | os.O_CLOEXEC | os.O_APPEND | _NOFOLLOW
        if create:
            flags |= os.O_CREAT
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            ) from exc
        try:
            self._validate_open_identity(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def _validate_open_identity(self, descriptor: int) -> None:
        try:
            opened = os.fstat(descriptor)
            current = self.path.lstat()
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            ) from exc
        if not (
            stat.S_ISREG(opened.st_mode)
            and opened.st_uid == os.getuid()
            and stat.S_IMODE(opened.st_mode) == 0o600
            and opened.st_nlink == 1
            and (opened.st_dev, opened.st_ino)
            == (current.st_dev, current.st_ino)
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            )

    @staticmethod
    def _validate_lock_identity(path: Path, descriptor: int) -> None:
        try:
            opened = os.fstat(descriptor)
            current = path.lstat()
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility workflow lock is invalid"
            ) from exc
        if not (
            stat.S_ISREG(opened.st_mode)
            and opened.st_uid == os.getuid()
            and stat.S_IMODE(opened.st_mode) == 0o600
            and opened.st_nlink == 1
            and opened.st_size == 0
            and (opened.st_dev, opened.st_ino)
            == (current.st_dev, current.st_ino)
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility workflow lock is invalid"
            )

    def _sync_parent(self) -> None:
        try:
            _fsync_directory(self.path.parent)
        except Exception as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger write failed"
            ) from exc

    def _read_records(self, descriptor: int) -> list[dict[str, Any]]:
        before = os.fstat(descriptor)
        size = before.st_size
        if size < 0 or size > _MAX_LEDGER_BYTES:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw_chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            raw_chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(raw_chunks)
        after = os.fstat(descriptor)
        self._validate_open_identity(descriptor)
        if (
            len(raw) != before.st_size
            or after.st_size != before.st_size
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            )
        if not raw:
            return []
        if not raw.endswith(b"\n"):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            )
        records: list[dict[str, Any]] = []
        for encoded_line in raw.splitlines():
            try:
                line = encoded_line.decode("utf-8")
                value = json.loads(
                    line,
                    object_pairs_hook=self._unique_json_object,
                )
            except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                ) from exc
            if (
                not isinstance(value, dict)
                or canonical_json(value).encode("utf-8") != encoded_line
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            records.append(value)
        if len(records) > _MAX_LEDGER_RECORDS:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility ledger is invalid"
            )
        previous: str | None = None
        starts: dict[int, dict[str, Any]] = {}
        completions: set[int] = set()
        correlation_hashes: set[str] = set()
        attempt_claimed = False
        for record_index, record in enumerate(records):
            expected_hash = record.get("record_sha256")
            unhashed = {
                key: value
                for key, value in record.items()
                if key != "record_sha256"
            }
            if (
                record.get("schema_version") != _SCHEMA_VERSION
                or record.get("previous_record_sha256") != previous
                or not isinstance(expected_hash, str)
                or canonical_sha256(unhashed) != expected_hash
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            if attempt_claimed:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            record_type = record.get("record_type")
            if record_type == "eligibility_cycle_started":
                cycle_number = len(starts) + 1
                correlation_hash = record.get(
                    "non_attempt_correlation_id_sha256"
                )
                if (
                    record.get("cycle_number") != cycle_number
                    or record.get("non_attempt_correlation_id") != "withheld"
                    or set(record)
                    != {
                        "schema_version",
                        "record_type",
                        "cycle_number",
                        "started_at",
                        "non_attempt_correlation_id",
                        "non_attempt_correlation_id_sha256",
                        "authorized_categories",
                        "category_call_limits",
                        "margin_source_read_limits",
                        "r12_claim_created",
                        "r12_idempotency_key_created",
                        "r12_attempt_consumed",
                        "preview_order_authorized",
                        "exchange_mutations_authorized",
                        "raw_response_included",
                        "external_exception_text_included",
                        "private_identifier_values_included",
                        "previous_record_sha256",
                        "record_sha256",
                    }
                    or record.get("authorized_categories")
                    != list(_ELIGIBILITY_CATEGORIES)
                    or not _exact_int_counters(
                        record.get("category_call_limits"),
                        _ELIGIBILITY_CALL_LIMITS,
                    )
                    or not _exact_int_counters(
                        record.get("margin_source_read_limits"),
                        FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS,
                    )
                    or record.get("r12_claim_created") is not False
                    or record.get("r12_idempotency_key_created") is not False
                    or record.get("r12_attempt_consumed") is not False
                    or record.get("preview_order_authorized") is not False
                    or record.get("exchange_mutations_authorized") is not False
                    or record.get("raw_response_included") is not False
                    or record.get("external_exception_text_included") is not False
                    or record.get("private_identifier_values_included") is not False
                    or not self._is_sha256(correlation_hash)
                    or correlation_hash in correlation_hashes
                    or self._parse_persisted_timestamp(record.get("started_at"))
                    is None
                ):
                    raise FuturesPreviewR12EligibilityError(
                        "R12 eligibility ledger is invalid"
                    )
                correlation_hashes.add(str(correlation_hash))
                starts[cycle_number] = record
            elif record_type == "eligibility_cycle_completed":
                cycle_number = record.get("cycle_number")
                outcome = record.get("outcome")
                classification = record.get("classification")
                attempts = record.get("call_attempts")
                started = starts.get(cycle_number)
                completed_at = self._parse_persisted_timestamp(
                    record.get("completed_at")
                )
                started_at = (
                    self._parse_persisted_timestamp(started.get("started_at"))
                    if started is not None
                    else None
                )
                if (
                    set(record)
                    != {
                        "schema_version",
                        "record_type",
                        "cycle_number",
                        "started_record_sha256",
                        "completed_at",
                        "outcome",
                        "classification",
                        "call_attempts",
                        "margin_source_read_limits",
                        "eligibility_evidence_sha256",
                        "r12_claim_created",
                        "r12_idempotency_key_created",
                        "r12_attempt_consumed",
                        "raw_response_included",
                        "external_exception_text_included",
                        "private_identifier_values_included",
                        "previous_record_sha256",
                        "record_sha256",
                    }
                    or not isinstance(cycle_number, int)
                    or started is None
                    or cycle_number in completions
                    or record.get("started_record_sha256")
                    != started.get("record_sha256")
                    or completed_at is None
                    or started_at is None
                    or completed_at < started_at
                    or (
                        outcome == "eligible"
                        and (completed_at - started_at).total_seconds()
                        > FUTURES_PREVIEW_R12_ELIGIBILITY_MAX_CYCLE_AGE_SECONDS
                    )
                    or outcome not in {"eligible", "ineligible", "unknown"}
                    or classification
                    not in _PERSISTED_COMPLETION_CLASSIFICATIONS
                    or not self._valid_completion_pair(outcome, classification)
                    or not isinstance(attempts, dict)
                    or set(attempts) != set(_ELIGIBILITY_CATEGORIES)
                    or any(
                        type(attempts.get(category)) is not int
                        or attempts.get(category) not in {0, 1}
                        for category in _ELIGIBILITY_CATEGORIES
                    )
                    or not _exact_int_counters(
                        record.get("margin_source_read_limits"),
                        FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS,
                    )
                    or (
                        outcome == "eligible"
                        and not _exact_int_counters(
                            attempts,
                            _ELIGIBILITY_CALL_LIMITS,
                        )
                    )
                    or (
                        outcome == "eligible"
                        and not self._is_sha256(
                            record.get("eligibility_evidence_sha256")
                        )
                    )
                    or (
                        outcome != "eligible"
                        and record.get("eligibility_evidence_sha256") is not None
                    )
                    or record.get("r12_claim_created") is not False
                    or record.get("r12_idempotency_key_created") is not False
                    or record.get("r12_attempt_consumed") is not False
                    or record.get("raw_response_included") is not False
                    or record.get("external_exception_text_included") is not False
                    or record.get("private_identifier_values_included") is not False
                ):
                    raise FuturesPreviewR12EligibilityError(
                        "R12 eligibility ledger is invalid"
                    )
                completions.add(cycle_number)
            elif record_type == "r12_attempt_claimed":
                cycle_number = record.get("cycle_number")
                completion = records[record_index - 1] if record_index > 0 else None
                claimed_at = self._parse_persisted_timestamp(
                    record.get("claimed_at")
                )
                completed_at = (
                    self._parse_persisted_timestamp(
                        completion.get("completed_at")
                    )
                    if isinstance(completion, dict)
                    else None
                )
                if (
                    attempt_claimed
                    or set(record)
                    != {
                        "schema_version",
                        "record_type",
                        "cycle_number",
                        "eligibility_completion_record_sha256",
                        "eligibility_evidence_sha256",
                        "claim_record_sha256",
                        "claimed_at",
                        "r12_claim_created",
                        "r12_idempotency_key_created",
                        "r12_attempt_consumed",
                        "additional_eligibility_reads_authorized",
                        "additional_coinbase_calls_authorized",
                        "raw_response_included",
                        "external_exception_text_included",
                        "private_identifier_values_included",
                        "previous_record_sha256",
                        "record_sha256",
                    }
                    or not isinstance(cycle_number, int)
                    or not isinstance(completion, dict)
                    or completion.get("record_type")
                    != "eligibility_cycle_completed"
                    or completion.get("cycle_number") != cycle_number
                    or completion.get("outcome") != "eligible"
                    or completion.get("record_sha256")
                    != record.get("eligibility_completion_record_sha256")
                    or completion.get("eligibility_evidence_sha256")
                    != record.get("eligibility_evidence_sha256")
                    or not self._is_sha256(record.get("claim_record_sha256"))
                    or claimed_at is None
                    or completed_at is None
                    or claimed_at < completed_at
                    or record.get("r12_claim_created") is not True
                    or record.get("r12_idempotency_key_created") is not True
                    or record.get("r12_attempt_consumed") is not True
                    or record.get("additional_eligibility_reads_authorized")
                    is not False
                    or record.get("additional_coinbase_calls_authorized")
                    is not False
                    or record.get("raw_response_included") is not False
                    or record.get("external_exception_text_included") is not False
                    or record.get("private_identifier_values_included") is not False
                ):
                    raise FuturesPreviewR12EligibilityError(
                        "R12 eligibility ledger is invalid"
                    )
                attempt_claimed = True
            else:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility ledger is invalid"
                )
            previous = str(expected_hash)
        return records

    @staticmethod
    def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    @staticmethod
    def _parse_persisted_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.endswith("Z"):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if (
            parsed.tzinfo is None
            or parsed.microsecond != 0
            or parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
            .replace("+00:00", "Z")
            != value
        ):
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _valid_completion_pair(outcome: Any, classification: Any) -> bool:
        if outcome == "eligible":
            return classification == "exact_v3_eligible"
        if outcome == "unknown":
            return classification in {
                "read_outcome_unknown",
                "internal_validation_blocked",
            }
        return classification in {
            "permission_or_portfolio_ineligible",
            "product_or_market_or_position_ineligible",
            "product_contract_ineligible",
            "market_book_ineligible",
            "position_exposure_ineligible",
            "candidate_caps_ineligible",
            "margin_collateral_ineligible",
            "internal_validation_blocked",
        }

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("ledger write failed")
            view = view[written:]

    @staticmethod
    def _validate_correlation_id(value: str) -> str:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility correlation is invalid"
            ) from exc
        if parsed.version != 4 or str(parsed) != value:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility correlation is invalid"
            )
        return value

    @staticmethod
    def _validate_timestamp(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility timestamp is invalid"
            )
        normalized = value.astimezone(timezone.utc)
        return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _is_sha256(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )


class FuturesPreviewR12EligibilityWorkflow:
    """Run one pre-claim R12 eligibility cycle under a workflow-wide lease."""

    def __init__(
        self,
        *,
        store: FuturesPreviewR12EligibilityStore,
        attempt_artifact_path: Path,
        rest_client_factory: Callable[[], Any],
        now: Callable[[], datetime],
        correlation_id_factory: Callable[[], str],
    ) -> None:
        self.store = store
        self.attempt_artifact_path = Path(attempt_artifact_path)
        self.rest_client_factory = rest_client_factory
        self.now = now
        self.correlation_id_factory = correlation_id_factory

    def run_cycle(
        self,
        *,
        attempt_workflow: FuturesPreviewR12AttemptWorkflow | None = None,
    ) -> dict[str, Any]:
        """Reserve first, invoke each category at most once, then close."""

        if attempt_workflow is not None:
            if type(attempt_workflow) is not FuturesPreviewR12AttemptWorkflow:
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility attempt workflow is invalid"
                )
            if (
                attempt_workflow.eligibility_store is not self.store
                or os.path.abspath(os.fspath(attempt_workflow.store.path))
                != os.path.abspath(os.fspath(self.attempt_artifact_path))
                or os.path.abspath(
                    os.fspath(attempt_workflow.eligibility_store.path)
                )
                != os.path.abspath(os.fspath(self.store.path))
            ):
                raise FuturesPreviewR12EligibilityError(
                    "R12 eligibility attempt workflow store or path is invalid"
                )
        with self.store.workflow_lease() as lease_nonce:
            self._assert_attempt_unclaimed()
            correlation_id = self.correlation_id_factory()
            started = self.store.begin_cycle(
                correlation_id=correlation_id,
                started_at=self.now(),
            )
            cycle_number = int(started["cycle_number"])
            correlation_sha256 = str(
                started["non_attempt_correlation_id_sha256"]
            )
            client: FuturesPreviewR12EligibilityClient | None = None
            try:
                delegate = self.rest_client_factory()
                transport_policy_evidence = (
                    validate_r12_zero_retry_redirect_transport(delegate)
                )
                client = FuturesPreviewR12EligibilityClient(
                    delegate,
                    _capability=_R12EligibilityCycleCapability(
                        store=self.store,
                        nonce=lease_nonce,
                        cycle_number=cycle_number,
                        start_sha256=str(started["record_sha256"]),
                    ),
                )
                permissions = _plain(client.get_api_key_permissions())
                portfolios = _plain(client.list_portfolios())
                product = _plain(
                    client.get_product_dict(FUTURES_PREVIEW_PRODUCT_ID)
                )
                book = _plain(
                    client.get_best_bid_ask(
                        product_ids=[FUTURES_PREVIEW_PRODUCT_ID]
                    )
                )
                positions = _plain(client.get_futures_positions())
                margin_collateral = _plain(
                    client.get_futures_margin_collateral_snapshot()
                )
            except Exception:
                return self._complete_failure(
                    cycle_number=cycle_number,
                    correlation_sha256=correlation_sha256,
                    outcome="unknown",
                    classification="read_outcome_unknown",
                    call_attempts=(
                        client.call_attempts
                        if client is not None
                        else {
                            category: 0 for category in _ELIGIBILITY_CATEGORIES
                        }
                    ),
                )

            observed_at = self.now()
            try:
                binding = evaluate_futures_default_portfolio_binding(
                    permissions=permissions,
                    portfolios=portfolios,
                    observed_at=_timestamp(observed_at),
                    permissions_read=True,
                    portfolio_catalog_read=True,
                )
                if (
                    not binding.read_ready
                    or binding.can_view is not True
                    or binding.can_trade is not True
                ):
                    raise ValueError("R12 eligibility portfolio blocked")
            except Exception:
                return self._complete_failure(
                    cycle_number=cycle_number,
                    correlation_sha256=correlation_sha256,
                    outcome="ineligible",
                    classification="permission_or_portfolio_ineligible",
                    call_attempts=client.call_attempts,
                )

            try:
                available_margin = validate_r12_margin_collateral_evidence(
                    margin_collateral
                )
            except Exception:
                return self._complete_failure(
                    cycle_number=cycle_number,
                    correlation_sha256=correlation_sha256,
                    outcome="ineligible",
                    classification="margin_collateral_ineligible",
                    call_attempts=client.call_attempts,
                )

            try:
                candidate = build_futures_order_preview_candidate(
                    product=_mapping(product),
                    book=_mapping(book),
                    positions=positions,
                    observed_at=observed_at,
                )
            except Exception as exc:
                return self._complete_failure(
                    cycle_number=cycle_number,
                    correlation_sha256=correlation_sha256,
                    outcome="ineligible",
                    classification=_candidate_failure_classification(exc),
                    call_attempts=client.call_attempts,
                )
            try:
                preview_request = _preview_request(candidate)
            except Exception:
                return self._complete_failure(
                    cycle_number=cycle_number,
                    correlation_sha256=correlation_sha256,
                    outcome="ineligible",
                    classification="internal_validation_blocked",
                    call_attempts=client.call_attempts,
                )

            try:
                completed_at = self.now()
                evidence = _r12_eligibility_evidence(
                    cycle_number=cycle_number,
                    started_at=str(started["started_at"]),
                    completed_at=completed_at,
                    correlation_sha256=correlation_sha256,
                    binding=binding.to_dict(),
                    product=product,
                    book=book,
                    positions=positions,
                    margin_collateral=margin_collateral,
                    available_margin=available_margin,
                    candidate=candidate,
                    preview_request=preview_request,
                    read_counters=client.call_attempts,
                    transport_policy_evidence=transport_policy_evidence,
                )
                evidence_sha256 = str(evidence["eligibility_evidence_sha256"])
                completion = self.store.complete_cycle(
                    cycle_number=cycle_number,
                    completed_at=completed_at,
                    outcome="eligible",
                    classification="exact_v3_eligible",
                    call_attempts=client.call_attempts,
                    eligibility_evidence_sha256=evidence_sha256,
                    _lease_nonce=lease_nonce,
                    _read_capability=client.completion_capability(),
                )
            except FuturesPreviewR12EligibilityError:
                raise
            except Exception:
                return self._complete_failure(
                    cycle_number=cycle_number,
                    correlation_sha256=correlation_sha256,
                    outcome="ineligible",
                    classification="internal_validation_blocked",
                    call_attempts=client.call_attempts,
                )
            result = {
                "status": "eligible",
                "classification": "exact_v3_eligible",
                "cycle_number": cycle_number,
                "non_attempt_correlation_id": "withheld",
                "non_attempt_correlation_id_sha256": correlation_sha256,
                "r12_claim_created": False,
                "r12_idempotency_key_created": False,
                "r12_attempt_consumed": False,
                "eligibility_evidence": deepcopy(evidence),
                "eligibility_evidence_sha256": evidence_sha256,
                "eligibility_completion_record_sha256": completion[
                    "record_sha256"
                ],
            }
            if attempt_workflow is not None:
                return attempt_workflow.run(
                    deepcopy(result),
                    _R12EligibilityTransitionCapability(
                        store=self.store,
                        nonce=lease_nonce,
                        cycle_number=cycle_number,
                        completion_sha256=str(completion["record_sha256"]),
                        attempt_artifact_path=self.attempt_artifact_path,
                        delegate=delegate,
                    ),
                )
            return result

    def _assert_attempt_unclaimed(self) -> None:
        try:
            self.attempt_artifact_path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt claim state is invalid"
            ) from exc
        raise FuturesPreviewR12EligibilityError(
            "R12 attempt is already claimed"
        )

    def _complete_failure(
        self,
        *,
        cycle_number: int,
        correlation_sha256: str,
        outcome: str,
        classification: str,
        call_attempts: Mapping[str, int],
    ) -> dict[str, Any]:
        self.store.complete_cycle(
            cycle_number=cycle_number,
            completed_at=self.now(),
            outcome=outcome,
            classification=classification,
            call_attempts=call_attempts,
            eligibility_evidence_sha256=None,
        )
        return {
            "status": outcome,
            "classification": classification,
            "cycle_number": cycle_number,
            "non_attempt_correlation_id": "withheld",
            "non_attempt_correlation_id_sha256": correlation_sha256,
            "r12_claim_created": False,
            "r12_idempotency_key_created": False,
            "r12_attempt_consumed": False,
        }


class FuturesPreviewR12AttemptWorkflow:
    """Create one R12 claim only from a fresh durable eligibility success."""

    def __init__(
        self,
        *,
        eligibility_store: FuturesPreviewR12EligibilityStore,
        store: FuturesOrderPreviewArtifactStore,
        predecessor_binding: Mapping[str, Any],
        predecessor_validator: Callable[[], Mapping[str, Any]],
        now: Callable[[], datetime],
        correlation_id_factory: Callable[[], str],
        idempotency_key_factory: Callable[[], str],
    ) -> None:
        if type(store) is not FuturesPreviewR12ArtifactStore:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt artifact store is invalid"
            )
        self.eligibility_store = eligibility_store
        self.store = store
        self.predecessor_binding = deepcopy(dict(predecessor_binding))
        self.predecessor_validator = predecessor_validator
        self.now = now
        self.correlation_id_factory = correlation_id_factory
        self.idempotency_key_factory = idempotency_key_factory

    def recover_claim_only(
        self,
        *,
        _lease_nonce: object | None = None,
    ) -> dict[str, Any] | None:
        """Terminalize a durable claim without making any Coinbase call."""

        self.eligibility_store.require_active_workflow_lease(_lease_nonce)
        self.store.normalize_atomic_claim_publication()

        try:
            self.store.path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            raise FuturesPreviewR12EligibilityError(
                "R12 recovery artifact state is invalid"
            ) from None
        try:
            rows = self.store._read_rows()  # noqa: SLF001
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 recovery artifact state is invalid"
            ) from None
        if len(rows) == 2:
            return self.store.read_completed()
        if (
            len(rows) != 1
            or rows[0].get("record_type") != "claim"
            or not isinstance(rows[0].get("record"), Mapping)
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 recovery artifact state is invalid"
            )
        claim = deepcopy(dict(rows[0]["record"]))
        claim_sha256 = rows[0].get("record_sha256")
        eligibility = self._validate_claim_only_recovery(
            claim=claim,
            claim_sha256=claim_sha256,
        )
        binding = _mapping(claim.get("non_attempt_eligibility_binding"))
        try:
            self.eligibility_store.mark_attempt_claimed(
                cycle_number=int(binding["cycle_number"]),
                completion_record_sha256=str(
                    binding["eligibility_completion_record_sha256"]
                ),
                claim_record_sha256=str(claim_sha256),
                claimed_at=self.now(),
            )
        except Exception:
            # The canonical attempt artifact remains the authoritative stop
            # signal even when the auxiliary eligibility marker is unavailable.
            pass
        terminal = self._terminal(
            claim=claim,
            claim_sha256=str(claim_sha256),
            eligibility=eligibility,
            outcome="unknown",
            blocker="claim_only_recovery_unknown_consumed",
            preview_order_attempt_count=1,
            post_preview_stage_evidence=None,
        )
        self._append_terminal(terminal, _lease_nonce=_lease_nonce)
        return self.store.read_completed()

    def run(
        self,
        eligible_result: Mapping[str, Any],
        _capability: _R12EligibilityTransitionCapability | None = None,
    ) -> dict[str, Any]:
        """Reserve once, issue only Preview, and always terminalize post-claim."""

        if type(_capability) is not _R12EligibilityTransitionCapability:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt requires an active eligibility transition"
            )
        if _capability.store is not self.eligibility_store:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility transition store is invalid"
            )
        if os.path.abspath(os.fspath(_capability.store.path)) != os.path.abspath(
            os.fspath(self.eligibility_store.path)
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility transition store is invalid"
            )
        if os.path.abspath(
            os.fspath(_capability.attempt_artifact_path)
        ) != os.path.abspath(os.fspath(self.store.path)):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility transition attempt path is invalid"
            )
        lease_nonce = _capability.active_lease_nonce()
        delegate = _capability.consume()
        eligibility = self.eligibility_store.validate_eligible_result(
            eligible_result
        )
        self._validate_eligibility_for_attempt(eligibility)
        try:
            observed_predecessor = dict(self.predecessor_validator())
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 predecessor validation blocked before claim"
            ) from None
        if observed_predecessor != self.predecessor_binding:
            raise FuturesPreviewR12EligibilityError(
                "R12 predecessor binding changed before claim"
            )
        self._validate_eligibility_for_attempt(eligibility)
        try:
            claim = self._build_claim(eligible_result, eligibility)
        except FuturesPreviewR12EligibilityError:
            raise

        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 claim construction blocked before claim"
            ) from None
        persisted_claim = self._withhold_claim(claim)
        self._validate_eligibility_for_attempt(eligibility)
        try:
            claim_sha256 = self.store.reserve(persisted_claim)
        except Exception:
            try:
                recovered = self.recover_claim_only(
                    _lease_nonce=lease_nonce,
                )
            except Exception:
                recovered = None
            if recovered is None:
                raise FuturesPreviewR12EligibilityError(
                    "R12 claim persistence blocked before claim"
                ) from None
            raise FuturesPreviewR12EligibilityError(
                "R12 claim persistence outcome unknown; attempt consumed"
            ) from None

        try:
            self.eligibility_store.mark_attempt_claimed(
                cycle_number=_capability.cycle_number,
                completion_record_sha256=_capability.completion_sha256,
                claim_record_sha256=claim_sha256,
                claimed_at=self.now(),
            )
        except Exception:
            terminal = self._terminal(
                claim=persisted_claim,
                claim_sha256=claim_sha256,
                eligibility=eligibility,
                outcome="unknown",
                blocker="eligibility_claim_marker_unknown_consumed",
                preview_order_attempt_count=0,
                post_preview_stage_evidence=None,
            )
            self._append_terminal(terminal, _lease_nonce=lease_nonce)
            raise FuturesPreviewR12EligibilityError(
                "R12 claim marker outcome unknown; attempt consumed"
            ) from None

        attempt_client: FuturesPreviewR12AttemptClient | None = None
        try:
            try:
                post_claim_predecessor = dict(self.predecessor_validator())
            except Exception:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="blocked",
                    blocker="predecessor_validation_blocked_after_claim",
                    preview_order_attempt_count=0,
                    post_preview_stage_evidence=None,
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 attempt blocked after claim; attempt consumed"
                ) from None
            if post_claim_predecessor != self.predecessor_binding:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="blocked",
                    blocker="predecessor_binding_changed_after_claim",
                    preview_order_attempt_count=0,
                    post_preview_stage_evidence=None,
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 attempt blocked after claim; attempt consumed"
                ) from None
            try:
                validate_r12_zero_retry_redirect_transport(delegate)
                attempt_client = FuturesPreviewR12AttemptClient(
                    delegate,
                    _capability=_R12AttemptClaimCapability(
                        store=self.store,
                        claim_sha256=claim_sha256,
                        preview_request=_mapping(
                            eligibility.get("preview_request")
                        ),
                    ),
                )
            except Exception:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="unknown",
                    blocker="preview_boundary_initialization_unknown_consumed",
                    preview_order_attempt_count=0,
                    post_preview_stage_evidence=None,
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 Preview outcome unknown; attempt consumed"
                ) from None
            try:
                raw_preview = attempt_client.preview_order()
            except Exception:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="unknown",
                    blocker="preview_order_unknown_consumed",
                    preview_order_attempt_count=1,
                    post_preview_stage_evidence=None,
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 Preview outcome unknown; attempt consumed"
                ) from None

            try:
                normalized_preview = (
                    validate_post_r10_preview_response_acceptance(raw_preview)
                )
            except Exception:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="blocked",
                    blocker="post_preview_stage_blocked",
                    preview_order_attempt_count=1,
                    post_preview_stage_evidence=self._stage_evidence(
                        stage="preview_response_validation",
                        reason_code=(
                            "futures_preview_response_validation_blocked"
                        ),
                    ),
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 Preview validation blocked; attempt consumed"
                ) from None
            try:
                normalized_preview = validate_preview_against_candidate(
                    normalized_preview,
                    _mapping(eligibility.get("candidate")),
                )
            except Exception:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="blocked",
                    blocker="post_preview_stage_blocked",
                    preview_order_attempt_count=1,
                    post_preview_stage_evidence=self._stage_evidence(
                        stage="candidate_cap_binding",
                        reason_code=(
                            "futures_preview_candidate_cap_binding_blocked"
                        ),
                    ),
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 Preview validation blocked; attempt consumed"
                ) from None
            try:
                available_margin = _decimal(
                    _mapping(
                        eligibility.get("margin_collateral_evidence")
                    ).get("available_margin_usdc"),
                    "available_margin",
                )
                preview_margin = _decimal(
                    normalized_preview.get("order_margin_total"),
                    "order_margin_total",
                )
                if (
                    not available_margin.is_finite()
                    or available_margin <= 0
                    or not preview_margin.is_finite()
                    or preview_margin < 0
                    or preview_margin > available_margin
                ):
                    raise ValueError("R12 available margin insufficient")
            except Exception:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="blocked",
                    blocker="post_preview_stage_blocked",
                    preview_order_attempt_count=1,
                    post_preview_stage_evidence=self._stage_evidence(
                        stage="available_margin_validation",
                        reason_code=(
                            "futures_preview_available_margin_validation_blocked"
                        ),
                    ),
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 Preview validation blocked; attempt consumed"
                ) from None

            preview_id = normalized_preview.get("preview_id")
            if (
                type(preview_id) is not str
                or not preview_id
                or preview_id == "withheld"
                or preview_id != preview_id.strip()
                or not preview_id.isprintable()
                or len(preview_id) > 256
            ):
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="blocked",
                    blocker="post_preview_stage_blocked",
                    preview_order_attempt_count=1,
                    post_preview_stage_evidence=self._stage_evidence(
                        stage="preview_identifier_binding",
                        reason_code=(
                            "futures_preview_identifier_binding_blocked"
                        ),
                    ),
                )
                self._append_terminal(
                    terminal,
                    _lease_nonce=lease_nonce,
                )
                raise FuturesPreviewR12EligibilityError(
                    "R12 Preview binding unavailable; attempt consumed"
                ) from None
            persisted_preview = deepcopy(dict(normalized_preview))
            persisted_preview["preview_id"] = "withheld"
            preview_id_sha256 = hashlib.sha256(
                preview_id.encode("utf-8")
            ).hexdigest()
            try:
                terminal_predecessor = dict(self.predecessor_validator())
            except Exception:
                terminal_predecessor = {}
            if terminal_predecessor != self.predecessor_binding:
                terminal = self._terminal(
                    claim=persisted_claim,
                    claim_sha256=claim_sha256,
                    eligibility=eligibility,
                    outcome="blocked",
                    blocker="terminal_predecessor_validation_blocked",
                    preview_order_attempt_count=1,
                    post_preview_stage_evidence=self._stage_evidence(
                        stage="terminal_predecessor_validation",
                        reason_code=(
                            "futures_preview_terminal_predecessor_blocked"
                        ),
                    ),
                )
                self._append_terminal(terminal, _lease_nonce=lease_nonce)
                raise FuturesPreviewR12EligibilityError(
                    "R12 terminal validation blocked; attempt consumed"
                ) from None
            terminal = self._terminal(
                claim=persisted_claim,
                claim_sha256=claim_sha256,
                eligibility=eligibility,
                outcome="accepted",
                blocker=None,
                preview_order_attempt_count=1,
                post_preview_stage_evidence=None,
                preview_response=persisted_preview,
                preview_id_sha256=preview_id_sha256,
            )
            self._append_terminal(terminal, _lease_nonce=lease_nonce)
            return self.store.read_completed()
        except FuturesPreviewR12EligibilityError:
            raise

    def _validate_claim_only_recovery(
        self,
        *,
        claim: Mapping[str, Any],
        claim_sha256: Any,
    ) -> dict[str, Any]:
        value = dict(claim)
        expected_keys = {
            "artifact_type",
            "claim_status",
            "predecessor_binding",
            "non_attempt_eligibility_binding",
            "non_attempt_eligibility",
            "non_attempt_eligibility_sha256",
            "preview_request_sha256",
            "reserved_at",
            "actor_id",
            "roles",
            "correlation_id",
            "correlation_id_sha256",
            "idempotency_key",
            "idempotency_key_sha256",
            "profile_label",
            "portfolio_type",
            "product_id",
            "contract_count",
            "caps",
            "allowed_coinbase_methods",
            "preview_order_attempt_max",
            "retry_attempt_max",
            "fallback_attempt_max",
            "create_order_attempt_max",
            "cancel_order_attempt_max",
            "close_position_attempt_max",
            "reduce_position_attempt_max",
            "post_claim_coinbase_read_max",
            "margin_window_policy_binding",
            "preview_response_schema_binding",
            "post_preview_diagnostic_binding",
            "slice3_activation_authorized",
            "slice4_activation_authorized",
            "slice5_activation_authorized",
            "marker_created",
            "ledger_created",
            "runtime_created",
        }
        eligibility = value.get("non_attempt_eligibility")
        binding = _mapping(value.get("non_attempt_eligibility_binding"))
        fixed_counters = {
            "preview_order_attempt_max": 1,
            "retry_attempt_max": 0,
            "fallback_attempt_max": 0,
            "create_order_attempt_max": 0,
            "cancel_order_attempt_max": 0,
            "close_position_attempt_max": 0,
            "reduce_position_attempt_max": 0,
            "post_claim_coinbase_read_max": 0,
        }
        if (
            set(value) != expected_keys
            or not FuturesPreviewR12EligibilityStore._is_sha256(claim_sha256)
            or value.get("artifact_type") != FUTURES_PREVIEW_R12_ARTIFACT_TYPE
            or value.get("claim_status") != "reserved"
            or value.get("predecessor_binding") != self.predecessor_binding
            or not isinstance(eligibility, Mapping)
            or value.get("non_attempt_eligibility_sha256")
            != eligibility.get("eligibility_evidence_sha256")
            or value.get("preview_request_sha256")
            != eligibility.get("preview_request_sha256")
            or value.get("actor_id") != FUTURES_PREVIEW_ACTOR_ID
            or value.get("roles") != [FUTURES_PREVIEW_ROLE]
            or value.get("correlation_id") != "withheld"
            or value.get("idempotency_key") != "withheld"
            or not FuturesPreviewR12EligibilityStore._is_sha256(
                value.get("correlation_id_sha256")
            )
            or not FuturesPreviewR12EligibilityStore._is_sha256(
                value.get("idempotency_key_sha256")
            )
            or value.get("correlation_id_sha256")
            == value.get("idempotency_key_sha256")
            or value.get("correlation_id_sha256")
            == eligibility.get("non_attempt_correlation_id_sha256")
            or value.get("idempotency_key_sha256")
            == eligibility.get("non_attempt_correlation_id_sha256")
            or value.get("profile_label") != "Default"
            or value.get("portfolio_type") != "DEFAULT"
            or value.get("product_id") != FUTURES_PREVIEW_PRODUCT_ID
            or value.get("contract_count") != "1"
            or value.get("caps")
            != {
                "opening_reference_notional_usdc": "100",
                "concurrent_exposure_usdc": "150",
                "buffered_close_reference_notional_usdc": "150",
                "branch_turnover_reference_notional_usdc": "300",
                "close_buffer_multiplier": "1.20",
                "comparison": "strictly_less_than",
            }
            or value.get("allowed_coinbase_methods") != ["preview_order"]
            or any(
                type(value.get(field)) is not int
                or value.get(field) != expected
                for field, expected in fixed_counters.items()
            )
            or value.get("margin_window_policy_binding")
            != FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
            or value.get("preview_response_schema_binding")
            != FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING
            or value.get("post_preview_diagnostic_binding")
            != FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING
            or any(
                value.get(field) is not False
                for field in (
                    "slice3_activation_authorized",
                    "slice4_activation_authorized",
                    "slice5_activation_authorized",
                    "marker_created",
                    "ledger_created",
                    "runtime_created",
                )
            )
            or set(binding)
            != {
                "cycle_number",
                "non_attempt_correlation_id",
                "non_attempt_correlation_id_sha256",
                "eligibility_evidence_sha256",
                "eligibility_completion_record_sha256",
                "completed_at",
            }
            or binding.get("cycle_number") != eligibility.get("cycle_number")
            or binding.get("non_attempt_correlation_id") != "withheld"
            or binding.get("non_attempt_correlation_id_sha256")
            != eligibility.get("non_attempt_correlation_id_sha256")
            or binding.get("eligibility_evidence_sha256")
            != eligibility.get("eligibility_evidence_sha256")
            or binding.get("completed_at") != eligibility.get("completed_at")
            or not FuturesPreviewR12EligibilityStore._is_sha256(
                binding.get("eligibility_completion_record_sha256")
            )
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 recovery claim is invalid"
            )
        self._parse_timestamp(value.get("reserved_at"))
        validated = deepcopy(dict(eligibility))
        self._validate_eligibility_for_attempt(
            validated,
            require_transition_freshness=False,
        )
        _R12AttemptClaimCapability(
            store=self.store,
            claim_sha256=str(claim_sha256),
            preview_request=_mapping(validated.get("preview_request")),
        ).consume()
        return validated

    def _build_claim(
        self,
        eligible_result: Mapping[str, Any],
        eligibility: Mapping[str, Any],
    ) -> dict[str, Any]:
        correlation_id = self.correlation_id_factory()
        idempotency_key = self.idempotency_key_factory()
        correlation_sha256 = self._validate_attempt_identifier(correlation_id)
        idempotency_sha256 = self._validate_attempt_identifier(idempotency_key)
        eligibility_correlation_sha256 = eligible_result.get(
            "non_attempt_correlation_id_sha256"
        )
        if (
            correlation_id == idempotency_key
            or correlation_sha256 == eligibility_correlation_sha256
            or idempotency_sha256 == eligibility_correlation_sha256
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt identifiers are not fresh"
            )
        return {
            "artifact_type": FUTURES_PREVIEW_R12_ARTIFACT_TYPE,
            "claim_status": "reserved",
            "predecessor_binding": deepcopy(self.predecessor_binding),
            "non_attempt_eligibility_binding": {
                "cycle_number": eligible_result["cycle_number"],
                "non_attempt_correlation_id": "withheld",
                "non_attempt_correlation_id_sha256": eligible_result[
                    "non_attempt_correlation_id_sha256"
                ],
                "eligibility_evidence_sha256": eligible_result[
                    "eligibility_evidence_sha256"
                ],
                "eligibility_completion_record_sha256": eligible_result[
                    "eligibility_completion_record_sha256"
                ],
                "completed_at": eligibility["completed_at"],
            },
            "non_attempt_eligibility": deepcopy(dict(eligibility)),
            "non_attempt_eligibility_sha256": eligibility[
                "eligibility_evidence_sha256"
            ],
            "preview_request_sha256": eligibility[
                "preview_request_sha256"
            ],
            "reserved_at": _timestamp(self.now()),
            "actor_id": FUTURES_PREVIEW_ACTOR_ID,
            "roles": [FUTURES_PREVIEW_ROLE],
            "correlation_id": correlation_id,
            "correlation_id_sha256": correlation_sha256,
            "idempotency_key": idempotency_key,
            "idempotency_key_sha256": idempotency_sha256,
            "profile_label": "Default",
            "portfolio_type": "DEFAULT",
            "product_id": FUTURES_PREVIEW_PRODUCT_ID,
            "contract_count": "1",
            "caps": {
                "opening_reference_notional_usdc": "100",
                "concurrent_exposure_usdc": "150",
                "buffered_close_reference_notional_usdc": "150",
                "branch_turnover_reference_notional_usdc": "300",
                "close_buffer_multiplier": "1.20",
                "comparison": "strictly_less_than",
            },
            "allowed_coinbase_methods": ["preview_order"],
            "preview_order_attempt_max": 1,
            "retry_attempt_max": 0,
            "fallback_attempt_max": 0,
            "create_order_attempt_max": 0,
            "cancel_order_attempt_max": 0,
            "close_position_attempt_max": 0,
            "reduce_position_attempt_max": 0,
            "post_claim_coinbase_read_max": 0,
            "margin_window_policy_binding": deepcopy(
                FUTURES_PREVIEW_R6_MARGIN_WINDOW_POLICY_BINDING
            ),
            "preview_response_schema_binding": deepcopy(
                FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING
            ),
            "post_preview_diagnostic_binding": deepcopy(
                FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING
            ),
            "slice3_activation_authorized": False,
            "slice4_activation_authorized": False,
            "slice5_activation_authorized": False,
            "marker_created": False,
            "ledger_created": False,
            "runtime_created": False,
        }

    @staticmethod
    def _withhold_claim(claim: Mapping[str, Any]) -> dict[str, Any]:
        result = deepcopy(dict(claim))
        for field in ("correlation_id", "idempotency_key"):
            if not isinstance(result.get(field), str):
                raise FuturesPreviewR12EligibilityError(
                    "R12 attempt identifier binding is invalid"
                )
            result[field] = "withheld"
        return result

    def _validate_eligibility_for_attempt(
        self,
        eligibility: Mapping[str, Any],
        *,
        require_transition_freshness: bool = True,
    ) -> None:
        value = dict(eligibility)
        expected_keys = {
            "schema_version",
            "type",
            "status",
            "classification",
            "cycle_number",
            "started_at",
            "completed_at",
            "non_attempt_correlation_id",
            "non_attempt_correlation_id_sha256",
            "profile_label",
            "portfolio_type",
            "portfolio_id",
            "portfolio_id_sha256",
            "portfolio_binding",
            "permission_evidence",
            "permission_evidence_sha256",
            "portfolio_catalog_evidence",
            "portfolio_catalog_evidence_sha256",
            "product_id",
            "product_evidence",
            "product_evidence_sha256",
            "market_evidence",
            "market_evidence_sha256",
            "position_evidence",
            "position_evidence_sha256",
            "margin_collateral_evidence",
            "margin_collateral_evidence_sha256",
            "margin_window_policy_evidence",
            "margin_window_policy_evidence_sha256",
            "transport_policy_evidence",
            "transport_policy_evidence_sha256",
            "candidate",
            "candidate_sha256",
            "preview_request",
            "preview_request_sha256",
            "read_counters",
            "margin_source_read_attempts",
            "sweep_evidence",
            "r12_claim_created",
            "r12_idempotency_key_created",
            "r12_attempt_consumed",
            "preview_order_attempt_count",
            "exchange_submission_attempt_count",
            "submitted_notional_usdc",
            "executed_notional_usdc",
            "read_only",
            "sanitized",
            "raw_response_included",
            "external_exception_text_included",
            "private_identifier_values_included",
            "canonicalization",
            "hash_algorithm",
            "eligibility_evidence_sha256",
        }
        if set(value) != expected_keys:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility is invalid"
            )
        started_at = self._parse_timestamp(value.get("started_at"))
        completed_at = self._parse_timestamp(eligibility.get("completed_at"))
        now = self.now().astimezone(timezone.utc)
        age = (now - completed_at).total_seconds()
        cycle_age = (completed_at - started_at).total_seconds()
        if (
            (
                require_transition_freshness
                and (
                    age < -1
                    or age
                    > FUTURES_PREVIEW_R12_ELIGIBILITY_MAX_TRANSITION_AGE_SECONDS
                )
            )
            or cycle_age < 0
            or cycle_age
            > FUTURES_PREVIEW_R12_ELIGIBILITY_MAX_CYCLE_AGE_SECONDS
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility is stale"
            )
        if (
            value.get("schema_version") != "1"
            or value.get("type")
            != "futures_preview_r12_non_attempt_eligibility"
            or value.get("status") != "eligible"
            or value.get("classification") != "exact_v3_eligible"
            or type(value.get("cycle_number")) is not int
            or not 1 <= value["cycle_number"] <= _MAX_CYCLES
            or value.get("product_id") != FUTURES_PREVIEW_PRODUCT_ID
            or value.get("profile_label") != "Default"
            or value.get("portfolio_type") != "DEFAULT"
            or value.get("portfolio_id") != "withheld"
            or not FuturesPreviewR12EligibilityStore._is_sha256(
                value.get("portfolio_id_sha256")
            )
            or value.get("non_attempt_correlation_id") != "withheld"
            or not FuturesPreviewR12EligibilityStore._is_sha256(
                value.get("non_attempt_correlation_id_sha256")
            )
            or not _exact_int_counters(
                value.get("read_counters"),
                _ELIGIBILITY_CALL_LIMITS,
            )
            or not _exact_int_counters(
                value.get("margin_source_read_attempts"),
                FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS,
            )
            or value.get("sweep_evidence")
            != "not_observed_not_authorized"
            or value.get("r12_claim_created") is not False
            or value.get("r12_idempotency_key_created") is not False
            or value.get("r12_attempt_consumed") is not False
            or type(value.get("preview_order_attempt_count")) is not int
            or value.get("preview_order_attempt_count") != 0
            or type(value.get("exchange_submission_attempt_count")) is not int
            or value.get("exchange_submission_attempt_count") != 0
            or value.get("submitted_notional_usdc") != "0"
            or value.get("executed_notional_usdc") != "0"
            or value.get("read_only") is not True
            or value.get("sanitized") is not True
            or value.get("raw_response_included") is not False
            or value.get("external_exception_text_included") is not False
            or value.get("private_identifier_values_included") is not False
            or value.get("canonicalization")
            != "sorted_keys_compact_utf8_json"
            or value.get("hash_algorithm") != "sha256"
            or "futures_sweeps" in canonical_json(value)
            or value.get("eligibility_evidence_sha256")
            != canonical_sha256(
                {
                    key: item
                    for key, item in value.items()
                    if key != "eligibility_evidence_sha256"
                }
            )
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility is invalid"
            )

        hash_bindings = (
            ("permission_evidence", "permission_evidence_sha256"),
            (
                "portfolio_catalog_evidence",
                "portfolio_catalog_evidence_sha256",
            ),
            ("product_evidence", "product_evidence_sha256"),
            ("market_evidence", "market_evidence_sha256"),
            ("position_evidence", "position_evidence_sha256"),
            (
                "margin_collateral_evidence",
                "margin_collateral_evidence_sha256",
            ),
            (
                "margin_window_policy_evidence",
                "margin_window_policy_evidence_sha256",
            ),
            (
                "transport_policy_evidence",
                "transport_policy_evidence_sha256",
            ),
            ("candidate", "candidate_sha256"),
            ("preview_request", "preview_request_sha256"),
        )
        if any(
            not isinstance(value.get(payload_field), Mapping)
            or value.get(digest_field)
            != canonical_sha256(value[payload_field])
            for payload_field, digest_field in hash_bindings
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility hash binding is invalid"
            )

        binding = _mapping(value.get("portfolio_binding"))
        binding_keys = {
            "status",
            "ready",
            "blocker",
            "read_authorized",
            "expected_portfolio_label",
            "expected_portfolio_type",
            "observed_portfolio_id",
            "observed_portfolio_label",
            "observed_portfolio_type",
            "can_view",
            "can_trade",
            "selection_authority",
            "request_portfolio_override_allowed",
            "source",
            "freshness_status",
            "observed_at",
            "permissions_read_ran",
            "portfolio_catalog_read_ran",
            "permissions_error_present",
            "portfolio_catalog_error_present",
            "account_family",
            "product_family",
            "profile_alias",
            "portfolio_id",
            "credential_trade_permission_present",
            "command_authority_granted",
            "live_coinbase_execution_authorized",
            "browser_authority",
            "bff_authority",
        }
        if (
            set(binding) != binding_keys
            or binding.get("status") != "matched"
            or binding.get("ready") is not True
            or binding.get("blocker") is not None
            or binding.get("read_authorized") is not True
            or binding.get("expected_portfolio_label") != "Default"
            or binding.get("expected_portfolio_type") != "DEFAULT"
            or binding.get("observed_portfolio_id") != "withheld"
            or binding.get("observed_portfolio_label") != "Default"
            or binding.get("observed_portfolio_type") != "DEFAULT"
            or binding.get("can_view") is not True
            or binding.get("can_trade") is not True
            or binding.get("selection_authority")
            != "cdp_api_key_permissioned_portfolio"
            or binding.get("request_portfolio_override_allowed") is not False
            or binding.get("source")
            != "coinbase_api_key_permissions_and_portfolio_catalog"
            or binding.get("freshness_status") != "backend_rest_fresh"
            or binding.get("permissions_read_ran") is not True
            or binding.get("portfolio_catalog_read_ran") is not True
            or binding.get("permissions_error_present") is not False
            or binding.get("portfolio_catalog_error_present") is not False
            or binding.get("account_family") != "coinbase_futures_us_cfm"
            or binding.get("product_family") != "FUTURES_PERPETUALS"
            or binding.get("profile_alias") != "Default"
            or binding.get("portfolio_id") != "withheld"
            or binding.get("credential_trade_permission_present") is not True
            or binding.get("command_authority_granted") is not False
            or binding.get("live_coinbase_execution_authorized") is not False
            or binding.get("browser_authority") != "display_only"
            or binding.get("bff_authority")
            != "forward_only_no_execution"
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility portfolio binding is invalid"
            )

        portfolio_sha256 = value["portfolio_id_sha256"]
        permission = _mapping(value.get("permission_evidence"))
        catalog = _mapping(value.get("portfolio_catalog_evidence"))
        if (
            set(permission)
            != {
                "portfolio_id",
                "portfolio_id_sha256",
                "portfolio_type",
                "can_view",
                "can_trade",
                "selection_authority",
                "sanitized",
                "raw_response_included",
            }
            or permission.get("portfolio_id") != "withheld"
            or permission.get("portfolio_id_sha256") != portfolio_sha256
            or permission.get("portfolio_type") != "DEFAULT"
            or permission.get("can_view") is not True
            or permission.get("can_trade") is not True
            or permission.get("selection_authority")
            != "cdp_api_key_permissioned_portfolio"
            or permission.get("sanitized") is not True
            or permission.get("raw_response_included") is not False
            or set(catalog)
            != {
                "selected_portfolio_id",
                "selected_portfolio_id_sha256",
                "selected_portfolio_label",
                "selected_portfolio_type",
                "exact_match_count",
                "sanitized",
                "raw_response_included",
            }
            or catalog.get("selected_portfolio_id") != "withheld"
            or catalog.get("selected_portfolio_id_sha256") != portfolio_sha256
            or catalog.get("selected_portfolio_label") != "Default"
            or catalog.get("selected_portfolio_type") != "DEFAULT"
            or type(catalog.get("exact_match_count")) is not int
            or catalog.get("exact_match_count") != 1
            or catalog.get("sanitized") is not True
            or catalog.get("raw_response_included") is not False
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility permission evidence is invalid"
            )

        product = _mapping(value.get("product_evidence"))
        product_details = _mapping(product.get("future_product_details"))
        if (
            set(product)
            != {
                "product_id",
                "display_name",
                "product_type",
                "status",
                "price",
                "price_increment",
                "base_increment",
                "base_min_size",
                "trading_disabled",
                "view_only",
                "cancel_only",
                "future_product_details",
                "sanitized",
                "raw_response_included",
            }
            or set(product_details)
            != {
                "contract_size",
                "contract_code",
                "group_description",
                "group_short_description",
                "venue",
                "risk_managed_by",
                "contract_expiry",
                "contract_expiry_type",
            }
            or product.get("sanitized") is not True
            or product.get("raw_response_included") is not False
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility product evidence is invalid"
            )

        market = _mapping(value.get("market_evidence"))
        position = _mapping(value.get("position_evidence"))
        if (
            set(market)
            != {
                "product_id",
                "best_bid",
                "best_ask",
                "exchange_observed_at",
                "sanitized",
                "raw_response_included",
            }
            or market.get("product_id") != FUTURES_PREVIEW_PRODUCT_ID
            or market.get("sanitized") is not True
            or market.get("raw_response_included") is not False
            or set(position)
            != {
                "product_id",
                "observed_contract_count",
                "sanitized",
                "raw_response_included",
            }
            or position.get("product_id") != FUTURES_PREVIEW_PRODUCT_ID
            or position.get("observed_contract_count") != "0"
            or position.get("sanitized") is not True
            or position.get("raw_response_included") is not False
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility market evidence is invalid"
            )

        margin = _mapping(value.get("margin_collateral_evidence"))
        margin_measure = _mapping(
            margin.get("intraday_margin_window_measure")
        )
        margin_setting = _mapping(margin.get("intraday_margin_setting"))
        margin_windows = margin.get("current_margin_windows")
        expected_margin_windows = [
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
                "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                "is_intraday_margin_killswitch_enabled": False,
                "is_intraday_margin_enrollment_killswitch_enabled": False,
            },
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
                "margin_window_type": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
                "is_intraday_margin_killswitch_enabled": False,
                "is_intraday_margin_enrollment_killswitch_enabled": False,
            },
        ]
        try:
            available_margin = _decimal(
                margin.get("available_margin_usdc"),
                "available_margin_usdc",
            )
            maintenance_margin = _decimal(
                margin_measure.get("maintenance_margin_usdc"),
                "maintenance_margin_usdc",
            )
            liquidation_buffer = _decimal(
                margin_measure.get("liquidation_buffer_usdc"),
                "liquidation_buffer_usdc",
            )
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility margin evidence is invalid"
            ) from None
        if (
            set(margin)
            != {
                "status",
                "account_family",
                "source",
                "source_read_attempts",
                "available_margin_usdc",
                "intraday_margin_window_measure",
                "intraday_margin_setting",
                "current_margin_windows",
                "sweep_evidence",
                "sanitized",
                "raw_response_included",
            }
            or margin.get("status") != "ready"
            or margin.get("account_family") != "coinbase_futures_us_cfm"
            or margin.get("source") != "backend_rest_client"
            or not _exact_int_counters(
                margin.get("source_read_attempts"),
                FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS,
            )
            or not available_margin.is_finite()
            or available_margin <= 0
            or set(margin_measure)
            != {
                "margin_window_type",
                "maintenance_margin_usdc",
                "liquidation_buffer_usdc",
            }
            or margin_measure.get("margin_window_type")
            != _R12_EXACT_FCM_MARGIN_WINDOW_TYPE
            or not maintenance_margin.is_finite()
            or maintenance_margin < 0
            or not liquidation_buffer.is_finite()
            or liquidation_buffer < 0
            or margin_setting
            != {"setting": _R12_EXACT_INTRADAY_MARGIN_SETTING}
            or margin_windows != expected_margin_windows
            or margin.get("sweep_evidence")
            != "not_observed_not_authorized"
            or margin.get("sanitized") is not True
            or margin.get("raw_response_included") is not False
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility margin evidence is invalid"
            )

        policy = _mapping(value.get("margin_window_policy_evidence"))
        if policy != {
            "policy_id": "slice2_preview_margin_window_exact_pair_policy_v3",
            "pair_policy_mode": "exact_profile_state_pair",
            "profile_state_policy_authority": (
                "operator_defined_slice_2_preview_only_not_coinbase_documented"
            ),
            "profile_state_mapping_documented_by_coinbase": False,
            "classification": "ready",
            "margin_window_policy_satisfied": True,
            "rows": [
                {
                    "policy_row_index": 0,
                    "recognized_profile": "retail_regular",
                    "observed_token": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
                    "documented_allowlist_match": True,
                    "operator_policy_match": True,
                    "classification": "accepted",
                },
                {
                    "policy_row_index": 1,
                    "recognized_profile": "retail_intraday_margin_1",
                    "observed_token": "MARGIN_WINDOW_TYPE_INTRADAY",
                    "documented_allowlist_match": True,
                    "operator_policy_match": True,
                    "classification": "accepted",
                },
            ],
            "r12_attempt_authority_granted": False,
            "sanitized": True,
            "raw_response_included": False,
        }:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility V3 policy evidence is invalid"
            )
        if not _valid_r12_transport_policy_evidence(
            value.get("transport_policy_evidence")
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility transport evidence is invalid"
            )

        candidate = _mapping(value.get("candidate"))
        preview_request = _mapping(value.get("preview_request"))
        observed_at = self._parse_timestamp(candidate.get("observed_at"))
        if (
            not started_at <= observed_at <= completed_at
            or binding.get("observed_at") != candidate.get("observed_at")
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility observation time is invalid"
            )
        product_source = {
            key: item
            for key, item in product.items()
            if key not in {"sanitized", "raw_response_included"}
        }
        book_source = {
            "pricebooks": [
                {
                    "product_id": market.get("product_id"),
                    "bids": [{"price": market.get("best_bid"), "size": "1"}],
                    "asks": [{"price": market.get("best_ask"), "size": "1"}],
                    "time": market.get("exchange_observed_at"),
                }
            ]
        }
        try:
            rebuilt_candidate = build_futures_order_preview_candidate(
                product=product_source,
                book=book_source,
                positions=[],
                observed_at=observed_at,
            )
            rebuilt_request = _preview_request(rebuilt_candidate)
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility candidate is invalid"
            ) from None
        if (
            candidate != rebuilt_candidate
            or preview_request != rebuilt_request
            or value.get("candidate_sha256")
            != canonical_sha256(rebuilt_candidate)
            or value.get("preview_request_sha256")
            != canonical_sha256(rebuilt_request)
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility candidate is invalid"
            )

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility timestamp is invalid"
            )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility timestamp is invalid"
            ) from exc
        if parsed.tzinfo is None:
            raise FuturesPreviewR12EligibilityError(
                "R12 eligibility timestamp is invalid"
            )
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _validate_attempt_identifier(value: str) -> str:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError) as exc:
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt identifiers are invalid"
            ) from exc
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if (
            parsed.version != 4
            or str(parsed) != value
            or digest in _R11_CONSUMED_PREVIEW_IDENTIFIER_SHA256
        ):
            raise FuturesPreviewR12EligibilityError(
                "R12 attempt identifiers are not fresh"
            )
        return digest

    def _terminal(
        self,
        *,
        claim: Mapping[str, Any],
        claim_sha256: str,
        eligibility: Mapping[str, Any],
        outcome: str,
        blocker: str | None,
        preview_order_attempt_count: int,
        post_preview_stage_evidence: Mapping[str, Any] | None,
        preview_response: Mapping[str, Any] | None = None,
        preview_id_sha256: str | None = None,
    ) -> dict[str, Any]:
        counters = {
            "preview_order": preview_order_attempt_count,
            "retry": 0,
            "fallback": 0,
            "create_order": 0,
            "cancel_order": 0,
            "close_position": 0,
            "reduce_position": 0,
        }
        try:
            completed_at = _timestamp(self.now())
        except BaseException:
            completed_at = str(claim.get("reserved_at") or "")
            self._parse_timestamp(completed_at)
        result: dict[str, Any] = {
            "schema_version": "1",
            "type": "admin_futures_order_preview",
            "artifact_type": FUTURES_PREVIEW_R12_ARTIFACT_TYPE,
            "status": outcome,
            "outcome": outcome,
            "blocker": blocker,
            "predecessor_binding": deepcopy(claim["predecessor_binding"]),
            "reserved_at": claim["reserved_at"],
            "completed_at": completed_at,
            "claim_sha256": claim_sha256,
            "actor_id": claim["actor_id"],
            "roles": list(claim["roles"]),
            "correlation_id": "withheld",
            "correlation_id_sha256": claim["correlation_id_sha256"],
            "idempotency_key": "withheld",
            "idempotency_key_sha256": claim["idempotency_key_sha256"],
            "profile_label": "Default",
            "portfolio_type": "DEFAULT",
            "product_id": FUTURES_PREVIEW_PRODUCT_ID,
            "non_attempt_eligibility": deepcopy(dict(eligibility)),
            "non_attempt_eligibility_sha256": eligibility[
                "eligibility_evidence_sha256"
            ],
            "candidate": deepcopy(dict(eligibility["candidate"])),
            "candidate_sha256": eligibility["candidate_sha256"],
            "preview_request": deepcopy(dict(eligibility["preview_request"])),
            "preview_request_sha256": eligibility["preview_request_sha256"],
            "preview_response": None,
            "preview_response_sha256": None,
            "preview_id_sha256": None,
            "attempt_counters": counters,
            "post_claim_read_counters": {
                category: 0 for category in _ELIGIBILITY_CATEGORIES
            },
            "eligibility_read_counters": deepcopy(
                dict(eligibility["read_counters"])
            ),
            "exchange_submission_attempt_count": 0,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "live_execution": "not_run",
            "live_coinbase_execution": "not_run",
            "read_only": True,
            "slice3_activation": "not_authorized",
            "slice4_activation": "not_authorized",
            "slice5_activation": "not_authorized",
            "r13_attempt_authorized": False,
            "post_preview_stage_evidence": (
                deepcopy(dict(post_preview_stage_evidence))
                if post_preview_stage_evidence is not None
                else None
            ),
            "post_preview_stage_evidence_sha256": (
                canonical_sha256(post_preview_stage_evidence)
                if post_preview_stage_evidence is not None
                else None
            ),
            "preview_response_schema_binding": deepcopy(
                FUTURES_PREVIEW_R11_RESPONSE_SCHEMA_BINDING
            ),
            "post_preview_diagnostic_binding": deepcopy(
                FUTURES_PREVIEW_R11_POST_PREVIEW_DIAGNOSTIC_BINDING
            ),
            "raw_response_included": False,
            "external_exception_text_included": False,
            "private_identifier_values_included": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "artifacts": {
                "execution_marker_created": False,
                "attempt_ledger_created": False,
                "runtime_created": False,
            },
            "canonicalization": "sorted_keys_compact_utf8_json",
            "hash_algorithm": "sha256",
        }
        if preview_response is not None:
            result["preview_response"] = deepcopy(dict(preview_response))
            result["preview_response_sha256"] = canonical_sha256(
                preview_response
            )
            result["preview_id_sha256"] = preview_id_sha256
        result["evidence_sha256"] = canonical_sha256(result)
        return result

    @staticmethod
    def _stage_evidence(*, stage: str, reason_code: str) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "source": "backend_futures_preview_r12_attempt",
            "stages": [
                {
                    "stage": stage,
                    "status": "blocked",
                    "reason_code": reason_code,
                }
            ],
            "sanitized": True,
            "raw_response_included": False,
            "external_exception_text_included": False,
            "identifier_values_included": False,
        }

    def _append_terminal(
        self,
        terminal: Mapping[str, Any],
        *,
        _lease_nonce: object | None,
    ) -> None:
        self.eligibility_store.require_active_workflow_lease(_lease_nonce)
        try:
            self.store.append_validated_terminal(terminal)
        except Exception:
            raise FuturesPreviewR12EligibilityError(
                "R12 terminal persistence unavailable; attempt consumed"
            ) from None


def _r12_eligibility_evidence(
    *,
    cycle_number: int,
    started_at: str,
    completed_at: datetime,
    correlation_sha256: str,
    binding: Mapping[str, Any],
    product: Any,
    book: Any,
    positions: Any,
    margin_collateral: Mapping[str, Any],
    available_margin: Decimal,
    candidate: Mapping[str, Any],
    preview_request: Mapping[str, Any],
    read_counters: Mapping[str, int],
    transport_policy_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the only successful, sanitized non-attempt R12 evidence."""

    started = FuturesPreviewR12AttemptWorkflow._parse_timestamp(started_at)
    completed = completed_at.astimezone(timezone.utc)
    duration = (completed - started).total_seconds()
    if (
        duration < 0
        or duration > FUTURES_PREVIEW_R12_ELIGIBILITY_MAX_CYCLE_AGE_SECONDS
        or not _exact_int_counters(read_counters, _ELIGIBILITY_CALL_LIMITS)
        or not _valid_r12_transport_policy_evidence(
            transport_policy_evidence
        )
    ):
        raise ValueError("R12 eligibility freshness is invalid")
    portfolio_id = binding.get("observed_portfolio_id")
    if not isinstance(portfolio_id, str) or not portfolio_id:
        raise ValueError("R12 eligibility portfolio binding unavailable")
    portfolio_id_sha256 = hashlib.sha256(
        portfolio_id.encode("utf-8")
    ).hexdigest()
    sanitized_binding = deepcopy(dict(binding))
    sanitized_binding["observed_portfolio_id"] = "withheld"
    sanitized_binding["portfolio_id"] = "withheld"
    permission_evidence = {
        "portfolio_id": "withheld",
        "portfolio_id_sha256": portfolio_id_sha256,
        "portfolio_type": binding.get("observed_portfolio_type"),
        "can_view": binding.get("can_view"),
        "can_trade": binding.get("can_trade"),
        "selection_authority": binding.get("selection_authority"),
        "sanitized": True,
        "raw_response_included": False,
    }
    portfolio_catalog_evidence = {
        "selected_portfolio_id": "withheld",
        "selected_portfolio_id_sha256": portfolio_id_sha256,
        "selected_portfolio_label": binding.get("observed_portfolio_label"),
        "selected_portfolio_type": binding.get("observed_portfolio_type"),
        "exact_match_count": 1,
        "sanitized": True,
        "raw_response_included": False,
    }
    product_evidence = _sanitized_product_evidence(product)
    market_evidence = _sanitized_market_evidence(book)
    position_evidence = _sanitized_position_evidence(positions)
    margin_evidence = _r12_sanitized_margin_evidence(
        margin_collateral,
        available_margin=available_margin,
    )
    policy = _classify_slice2_preview_margin_windows_policy(
        margin_collateral,
        policy_version="v3",
    )
    policy_evidence = {
        "policy_id": "slice2_preview_margin_window_exact_pair_policy_v3",
        "pair_policy_mode": "exact_profile_state_pair",
        "profile_state_policy_authority": (
            "operator_defined_slice_2_preview_only_not_coinbase_documented"
        ),
        "profile_state_mapping_documented_by_coinbase": False,
        "classification": policy.get("classification"),
        "margin_window_policy_satisfied": policy.get(
            "margin_window_policy_satisfied"
        ),
        "rows": deepcopy(policy.get("rows")),
        "r12_attempt_authority_granted": False,
        "sanitized": True,
        "raw_response_included": False,
    }
    evidence: dict[str, Any] = {
        "schema_version": "1",
        "type": "futures_preview_r12_non_attempt_eligibility",
        "status": "eligible",
        "classification": "exact_v3_eligible",
        "cycle_number": cycle_number,
        "started_at": started_at,
        "completed_at": _timestamp(completed_at),
        "non_attempt_correlation_id": "withheld",
        "non_attempt_correlation_id_sha256": correlation_sha256,
        "profile_label": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id": "withheld",
        "portfolio_id_sha256": portfolio_id_sha256,
        "portfolio_binding": sanitized_binding,
        "permission_evidence": permission_evidence,
        "permission_evidence_sha256": canonical_sha256(permission_evidence),
        "portfolio_catalog_evidence": portfolio_catalog_evidence,
        "portfolio_catalog_evidence_sha256": canonical_sha256(
            portfolio_catalog_evidence
        ),
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "product_evidence": product_evidence,
        "product_evidence_sha256": canonical_sha256(product_evidence),
        "market_evidence": market_evidence,
        "market_evidence_sha256": canonical_sha256(market_evidence),
        "position_evidence": position_evidence,
        "position_evidence_sha256": canonical_sha256(position_evidence),
        "margin_collateral_evidence": margin_evidence,
        "margin_collateral_evidence_sha256": canonical_sha256(
            margin_evidence
        ),
        "margin_window_policy_evidence": policy_evidence,
        "margin_window_policy_evidence_sha256": canonical_sha256(
            policy_evidence
        ),
        "transport_policy_evidence": deepcopy(
            dict(transport_policy_evidence)
        ),
        "transport_policy_evidence_sha256": canonical_sha256(
            transport_policy_evidence
        ),
        "candidate": dict(candidate),
        "candidate_sha256": canonical_sha256(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
        "read_counters": dict(read_counters),
        "margin_source_read_attempts": dict(
            FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS
        ),
        "sweep_evidence": "not_observed_not_authorized",
        "r12_claim_created": False,
        "r12_idempotency_key_created": False,
        "r12_attempt_consumed": False,
        "preview_order_attempt_count": 0,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "read_only": True,
        "sanitized": True,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "private_identifier_values_included": False,
        "canonicalization": "sorted_keys_compact_utf8_json",
        "hash_algorithm": "sha256",
    }
    evidence["eligibility_evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def _r12_sanitized_margin_evidence(
    value: Mapping[str, Any],
    *,
    available_margin: Decimal,
) -> dict[str, Any]:
    evidence = _mapping(value)
    if "futures_sweeps" in evidence:
        raise ValueError("R12 eligibility sweep evidence is not authorized")
    summary = _mapping(evidence.get("balance_summary"))
    measure = _mapping(summary.get("intraday_margin_window_measure"))
    setting = _mapping(evidence.get("intraday_margin_setting"))
    windows: list[dict[str, Any]] = []
    raw_windows = evidence.get("current_margin_windows")
    if not isinstance(raw_windows, list):
        raise ValueError("R12 eligibility margin windows unavailable")
    for item in raw_windows:
        window = _mapping(item)
        margin_window = _mapping(window.get("margin_window"))
        windows.append(
            {
                "profile": window.get("profile"),
                "margin_window_type": margin_window.get(
                    "margin_window_type"
                ),
                "is_intraday_margin_killswitch_enabled": window.get(
                    "is_intraday_margin_killswitch_enabled"
                ),
                "is_intraday_margin_enrollment_killswitch_enabled": window.get(
                    "is_intraday_margin_enrollment_killswitch_enabled"
                ),
            }
        )
    windows.sort(key=lambda item: str(item["profile"]))
    return {
        "status": evidence.get("status"),
        "account_family": evidence.get("account_family"),
        "source": evidence.get("source"),
        "source_read_attempts": dict(
            FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS
        ),
        "available_margin_usdc": _decimal_text(available_margin),
        "intraday_margin_window_measure": {
            "margin_window_type": measure.get("margin_window_type"),
            "maintenance_margin_usdc": _decimal_text(
                _decimal(
                    measure.get("maintenance_margin"),
                    "maintenance_margin",
                )
            ),
            "liquidation_buffer_usdc": _decimal_text(
                _decimal(
                    measure.get("liquidation_buffer"),
                    "liquidation_buffer",
                )
            ),
        },
        "intraday_margin_setting": {"setting": setting.get("setting")},
        "current_margin_windows": windows,
        "sweep_evidence": "not_observed_not_authorized",
        "sanitized": True,
        "raw_response_included": False,
    }
