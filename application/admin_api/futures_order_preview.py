"""One-shot, no-live Futures order Preview evidence.

The producer is a backend-only boundary.  It reserves one append-only JSONL
artifact before any Coinbase SDK read, performs fixed Default-profile AVAX CFM
preflight reads, and may make at most one ``Preview Order`` call.  The repeated
Admin API GET reads only the completed artifact and never receives a REST
client.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from uuid import uuid4

from application.admin_api.futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
)


FUTURES_PREVIEW_PRODUCT_ID = "AVP-20DEC30-CDE"
FUTURES_PREVIEW_ACTOR_ID = "operator-controlled-futures-proof"
FUTURES_PREVIEW_ROLE = "trader"
FUTURES_PREVIEW_CONTRACT_COUNT = Decimal("1")
FUTURES_PREVIEW_OPENING_CAP_USDC = Decimal("100")
FUTURES_PREVIEW_EXPOSURE_CAP_USDC = Decimal("150")
FUTURES_PREVIEW_TURNOVER_CAP_USDC = Decimal("300")
FUTURES_PREVIEW_CLOSE_BUFFER = Decimal("1.20")
FUTURES_PREVIEW_ARTIFACT_ENV = (
    "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH"
)
FUTURES_PREVIEW_ORIGINAL_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "futures_exact_no_live_preview_slice_2.jsonl"
)
FUTURES_PREVIEW_R1_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "futures_exact_no_live_preview_slice_2r1.jsonl"
)
FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "futures_exact_no_live_preview_slice_2r2.jsonl"
)
DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "futures_exact_no_live_preview_slice_2r3.jsonl"
)
FUTURES_PREVIEW_R3_ARTIFACT_PATH = DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH
FUTURES_PREVIEW_R4_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "futures_exact_no_live_preview_slice_2r4.jsonl"
)
FUTURES_PREVIEW_R1_FILE_SHA256 = (
    "55c09c6d4819f2d03dd679ae4c952e203cf540d1a141e13035459821f1b680d7"
)
FUTURES_PREVIEW_R1_EVIDENCE_SHA256 = (
    "a1b7820aa217b7119a6353a8f4fbffa5227ebfe5e4c8d8a1cde5449d370fc6f0"
)
FUTURES_PREVIEW_R1_DEVICE = 66305
FUTURES_PREVIEW_R1_INODE = 42312970
FUTURES_PREVIEW_R1_SIZE = 4197
FUTURES_PREVIEW_R1_MODE = 0o400
FUTURES_PREVIEW_R1_MTIME_NS = 1783980960753782357
FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256 = (
    "1831b2feaac69b9d3d64377123833831c1b1c1f26c1c0445ed17f334746b4053"
)
FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256 = (
    "afebf81c4d95c0abd7635fd700f6618e92191423173df3e2db0f875102b6f1c9"
)
FUTURES_PREVIEW_PREDECESSOR_DEVICE = 66305
FUTURES_PREVIEW_PREDECESSOR_INODE = 42312480
FUTURES_PREVIEW_PREDECESSOR_SIZE = 6002
FUTURES_PREVIEW_PREDECESSOR_MODE = 0o400
FUTURES_PREVIEW_PREDECESSOR_MTIME_NS = 1783991637010957407
FUTURES_PREVIEW_R3_FILE_SHA256 = (
    "7ccd5411878842f883b78a99a4103b9b7b1f9aa000ebdde29cdecf2ac894b61c"
)
FUTURES_PREVIEW_R3_EVIDENCE_SHA256 = (
    "e79beb3d9f1324cf8f90ba78cd45869fec5b7963afe3745bd6e26617313718e8"
)
FUTURES_PREVIEW_R3_DEVICE = 66305
FUTURES_PREVIEW_R3_INODE = 42312497
FUTURES_PREVIEW_R3_SIZE = 7616
FUTURES_PREVIEW_R3_MODE = 0o400
FUTURES_PREVIEW_R3_MTIME_NS = 1784054457360155278
FUTURES_PREVIEW_ORIGINAL_FILE_SHA256 = (
    "9b15da86c172eca46d4b3dc0fc2b81e9b325df9a1e2f75fef79362f538e2d5ff"
)
FUTURES_PREVIEW_ORIGINAL_EVIDENCE_SHA256 = (
    "3b09cb9dfe02991dc886a1c6f041330d417ff11a0f1d45e3734bdc59bfb219b8"
)
FUTURES_PREVIEW_ORIGINAL_DEVICE = 66305
FUTURES_PREVIEW_ORIGINAL_INODE = 42312964
FUTURES_PREVIEW_ORIGINAL_SIZE = 3043
FUTURES_PREVIEW_ORIGINAL_MODE = 0o400
FUTURES_PREVIEW_ORIGINAL_MTIME_NS = 1783968539951853688
_SCHEMA_VERSION = "1"
_ARTIFACT_TYPE = "futures_exact_no_live_preview_slice_2r3"
FUTURES_PREVIEW_R4_ARTIFACT_TYPE = (
    "futures_exact_no_live_preview_slice_2r4"
)
_R4_ARTIFACT_TYPE = FUTURES_PREVIEW_R4_ARTIFACT_TYPE
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS = frozenset(
    {
        "INTRADAY_MARGIN_SETTING_UNSPECIFIED",
        "INTRADAY_MARGIN_SETTING_STANDARD",
        "INTRADAY_MARGIN_SETTING_INTRADAY",
    }
)
FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS = frozenset(
    {
        "INTRADAY_MARGIN_SETTING_STANDARD",
        "INTRADAY_MARGIN_SETTING_INTRADAY",
    }
)
FUTURES_PREVIEW_OPERATIONAL_FCM_MARGIN_WINDOW_TYPES = frozenset(
    {
        "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT",
        "FCM_MARGIN_WINDOW_TYPE_WEEKEND",
        "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
        "FCM_MARGIN_WINDOW_TYPE_TRANSITION",
    }
)
FUTURES_PREVIEW_OPERATIONAL_CURRENT_MARGIN_WINDOW_TYPES = frozenset(
    {"MARGIN_WINDOW_TYPE_INTRADAY"}
)
FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES = {
    "MARGIN_PROFILE_TYPE_RETAIL_REGULAR": "retail_regular",
    "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1": (
        "retail_intraday_margin_1"
    ),
}
FUTURES_PREVIEW_EXPECTED_MARGIN_SOURCE_READS = {
    "get_futures_balance_summary": 1,
    "get_intraday_margin_setting": 1,
    "get_current_margin_window": 2,
    "list_futures_sweeps": 1,
}
FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2.jsonl",
    "file_sha256": FUTURES_PREVIEW_ORIGINAL_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_ORIGINAL_EVIDENCE_SHA256,
    "device": "66305",
    "inode": "42312964",
    "size_bytes": 3043,
    "mode": "0400",
    "mtime_ns": "1783968539951853688",
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
}
FUTURES_PREVIEW_R1_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r1.jsonl",
    "file_sha256": FUTURES_PREVIEW_R1_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R1_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R1_DEVICE),
    "inode": str(FUTURES_PREVIEW_R1_INODE),
    "size_bytes": FUTURES_PREVIEW_R1_SIZE,
    "mode": f"{FUTURES_PREVIEW_R1_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R1_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": (
        FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING
    ),
}
FUTURES_PREVIEW_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r2.jsonl",
    "file_sha256": FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_PREDECESSOR_DEVICE),
    "inode": str(FUTURES_PREVIEW_PREDECESSOR_INODE),
    "size_bytes": FUTURES_PREVIEW_PREDECESSOR_SIZE,
    "mode": f"{FUTURES_PREVIEW_PREDECESSOR_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_PREDECESSOR_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_R1_PREDECESSOR_BINDING,
}
FUTURES_PREVIEW_R3_PREDECESSOR_BINDING = {
    "artifact_name": "futures_exact_no_live_preview_slice_2r3.jsonl",
    "file_sha256": FUTURES_PREVIEW_R3_FILE_SHA256,
    "evidence_sha256": FUTURES_PREVIEW_R3_EVIDENCE_SHA256,
    "device": str(FUTURES_PREVIEW_R3_DEVICE),
    "inode": str(FUTURES_PREVIEW_R3_INODE),
    "size_bytes": FUTURES_PREVIEW_R3_SIZE,
    "mode": f"{FUTURES_PREVIEW_R3_MODE:04o}",
    "mtime_ns": str(FUTURES_PREVIEW_R3_MTIME_NS),
    "status": "blocked",
    "outcome": "blocked",
    "preview_order_attempt_count": 0,
    "exchange_submission_attempt_count": 0,
    "submitted_notional_usdc": "0",
    "executed_notional_usdc": "0",
    "preservation": "immutable_no_modify_delete_or_reuse",
    "original_predecessor_binding": FUTURES_PREVIEW_PREDECESSOR_BINDING,
}
_CONSUMED_PREVIEW_IDENTIFIERS = frozenset(
    {
        "9c26aed6-fce5-470b-b57e-b89423ecc0ed",
        "1396cd8f-d258-446f-92e1-fc53f6b93c71",
        "5dcd3d52-95bf-4fd3-93ca-83e8be28f132",
        "d1a930f2-0e91-42e0-8a22-a20444575585",
        "6cfffc61-2d69-4559-8729-ad3c5a8f9751",
        "f26dbcc6-4336-4bb1-a317-6c5a3d87d2d0",
    }
)
_SAFE_MARGIN_SETTING_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_MARGIN_WINDOW_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SDK_MARGIN_SETTING_FIELDS = {
    "setting",
    "rate_limit_remaining",
    "rate_limit_reset",
    "rate_limit_limit",
}
_PRE_PREVIEW_STAGE_ORDER = (
    "remaining_margin_validation",
    "candidate_construction",
    "preview_request_construction",
    "terminal_context_sanitization",
)
_PRE_PREVIEW_STAGE_FALLBACK_REASONS = {
    "remaining_margin_validation": (
        "futures_preview_remaining_margin_validation_unclassified"
    ),
    "candidate_construction": (
        "futures_preview_candidate_construction_unclassified"
    ),
    "preview_request_construction": (
        "futures_preview_request_construction_unclassified"
    ),
    "terminal_context_sanitization": (
        "futures_preview_terminal_context_sanitization_unclassified"
    ),
}
_PRE_PREVIEW_STAGE_ALLOWLISTED_REASONS = {
    "remaining_margin_validation": frozenset(
        {
            "futures_preview_margin_collateral_ambiguous",
            "futures_preview_margin_source_reads_ambiguous",
            "futures_preview_available_margin_currency_invalid",
            "futures_preview_available_margin_invalid",
            "futures_preview_total_usd_balance_currency_invalid",
            "futures_preview_total_usd_balance_invalid",
            "futures_preview_cfm_usd_balance_currency_invalid",
            "futures_preview_cfm_usd_balance_invalid",
            "futures_preview_futures_buying_power_currency_invalid",
            "futures_preview_futures_buying_power_invalid",
            "futures_preview_initial_margin_currency_invalid",
            "futures_preview_initial_margin_invalid",
            "futures_preview_liquidation_threshold_currency_invalid",
            "futures_preview_liquidation_threshold_invalid",
            "futures_preview_margin_window_measure_ambiguous",
            "futures_preview_maintenance_margin_invalid",
            "futures_preview_liquidation_buffer_invalid",
            "futures_preview_margin_maintenance_margin_invalid",
            "futures_preview_margin_liquidation_buffer_invalid",
            "futures_preview_margin_setting_ambiguous",
            "futures_preview_margin_setting_unspecified",
            "futures_preview_margin_windows_ambiguous",
            "futures_preview_margin_killswitch_ambiguous",
            "futures_preview_margin_killswitch_enabled",
            "futures_preview_margin_sweeps_ambiguous",
            "futures_preview_available_margin_not_positive",
        }
    ),
    "candidate_construction": frozenset(
        {
            "futures_preview_product_identity_blocked",
            "futures_preview_avp_display_name_blocked",
            "futures_preview_product_type_blocked",
            "futures_preview_product_status_blocked",
            "futures_preview_product_trading_blocked",
            "futures_preview_avp_perp_style_identity_blocked",
            "futures_preview_contract_size_invalid",
            "futures_preview_avp_contract_size_blocked",
            "futures_preview_product_price_invalid",
            "futures_preview_price_increment_invalid",
            "futures_preview_base_increment_invalid",
            "futures_preview_base_min_size_invalid",
            "futures_preview_one_contract_rule_blocked",
            "futures_preview_pricebook_missing",
            "futures_preview_pricebook_ambiguous",
            "futures_preview_market_time_missing",
            "futures_preview_market_time_invalid",
            "futures_preview_market_time_unzoned",
            "futures_preview_market_stale",
            "futures_preview_bids_missing",
            "futures_preview_bids_price_invalid",
            "futures_preview_asks_missing",
            "futures_preview_asks_price_invalid",
            "futures_preview_crossed_or_ambiguous_book",
            "futures_preview_best_bid_tick_misaligned",
            "futures_preview_limit_tick_blocked",
            "futures_preview_positions_ambiguous",
            "futures_preview_position_contracts_invalid",
            "futures_preview_existing_product_exposure_blocked",
            "futures_preview_opening_cap_blocked",
            "futures_preview_exposure_cap_blocked",
            "futures_preview_buffered_close_cap_blocked",
            "futures_preview_turnover_cap_blocked",
        }
    ),
    "preview_request_construction": frozenset(),
    "terminal_context_sanitization": frozenset(),
}
_TERMINAL_FAILURE_CONTEXT_ALLOWED_KEYS = frozenset(
    {
        "portfolio_id",
        "portfolio_binding",
        "permission_evidence",
        "permission_evidence_sha256",
        "portfolio_catalog_evidence",
        "portfolio_catalog_sha256",
        "product_evidence",
        "product_evidence_sha256",
        "market_evidence",
        "market_evidence_sha256",
        "position_evidence",
        "position_evidence_sha256",
        "margin_collateral_evidence",
        "margin_collateral_evidence_sha256",
        "margin_setting_evidence",
        "margin_setting_evidence_sha256",
        "margin_windows_evidence",
        "margin_windows_evidence_sha256",
        "candidate",
        "candidate_sha256",
        "preview_request",
        "preview_request_sha256",
        "preview_response",
        "preview_response_sha256",
    }
)


class FuturesOrderPreviewArtifactError(RuntimeError):
    """Raised when one-shot Preview evidence is unavailable or unsafe."""


def _redacted_preflight_blocker(exc: Exception) -> str:
    """Return only an exception type label, never response text."""

    return f"preflight_or_preview_blocked:{type(exc).__name__}"


def _pre_preview_stage_failure_context(
    *,
    passed_stages: Sequence[str],
    blocked_stage: str,
    exc: Exception,
) -> dict[str, Any]:
    """Return fixed, sanitized stage evidence without inspecting exception text."""

    reason = _PRE_PREVIEW_STAGE_FALLBACK_REASONS[blocked_stage]
    if (
        type(exc) is ValueError
        and len(exc.args) == 1
        and isinstance(exc.args[0], str)
        and exc.args[0]
        in _PRE_PREVIEW_STAGE_ALLOWLISTED_REASONS[blocked_stage]
    ):
        reason = exc.args[0]
    stages = [
        {"stage": stage, "status": "passed", "reason_code": None}
        for stage in passed_stages
    ]
    stages.append(
        {
            "stage": blocked_stage,
            "status": "blocked",
            "reason_code": reason,
        }
    )
    diagnostic = {
        "schema_version": "1",
        "source": "backend_futures_preview_producer",
        "stages": stages,
        "sanitized": True,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "identifier_values_included": False,
    }
    return {
        "pre_preview_stage_evidence": diagnostic,
        "pre_preview_stage_evidence_sha256": canonical_sha256(diagnostic),
    }


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_plain(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        return _plain(converter())
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    """Return deterministic compact UTF-8 JSON text."""

    return json.dumps(
        _plain(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    """Return SHA-256 for the canonical JSON representation."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def configured_futures_order_preview_artifact_path() -> Path:
    """Resolve the backend-owned immutable evidence path."""

    configured = os.environ.get(FUTURES_PREVIEW_ARTIFACT_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH


class FuturesOrderPreviewArtifactStore:
    """One-file append-only claim/result store with fail-closed reads."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def reserve(self, claim: Mapping[str, Any]) -> str:
        """Exclusively create and fsync the one-use attempt claim."""

        self._prepare_parent()
        try:
            current = self.path.lstat()
        except FileNotFoundError:
            current = None
        if current is not None:
            if stat.S_ISLNK(current.st_mode):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact path is a symlink"
                )
            raise FuturesOrderPreviewArtifactError(
                "futures Preview attempt is already consumed"
            )

        wrapped = self._record("claim", claim)
        payload = (canonical_json(wrapped) + "\n").encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview attempt is already consumed"
            ) from exc
        except OSError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact reservation failed"
            ) from exc
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_directory(self.path.parent)
        return str(wrapped["record_sha256"])

    def append_result(self, result: Mapping[str, Any]) -> str:
        """Append exactly one terminal result after a valid claim."""

        rows = self._read_rows()
        if len(rows) != 1 or rows[0].get("record_type") != "claim":
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact result cannot be appended"
            )
        claim_sha256 = str(rows[0]["record_sha256"])
        wrapped = self._record(
            "result",
            result,
            previous_record_sha256=claim_sha256,
        )
        if "outcome" in result:
            wrapped["outcome"] = str(result["outcome"])
            wrapped["record_sha256"] = _record_sha256(wrapped)
        payload = (canonical_json(wrapped) + "\n").encode("utf-8")

        before = self._safe_regular_lstat()
        flags = os.O_WRONLY | os.O_APPEND | _NOFOLLOW
        try:
            fd = os.open(self.path, flags)
        except OSError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact result append failed"
            ) from exc
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact identity changed"
                )
            _write_all(fd, payload)
            os.fsync(fd)
            os.fchmod(fd, 0o400)
        finally:
            os.close(fd)
        _fsync_directory(self.path.parent)
        return str(wrapped["record_sha256"])

    def read_completed(self) -> dict[str, Any]:
        """Return a valid terminal accepted, blocked, or unknown record."""

        rows = self._read_rows()
        if len(rows) != 2:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is not completed"
            )
        terminal = self._safe_regular_lstat()
        if stat.S_IMODE(terminal.st_mode) != 0o400:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview completed artifact mode is invalid"
            )
        claim, result = rows
        if (
            claim.get("record_type") != "claim"
            or result.get("record_type") != "result"
            or result.get("previous_record_sha256") != claim.get("record_sha256")
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact chain is tampered"
            )
        record = result.get("record")
        if result.get("outcome") not in {"accepted", "blocked", "unknown"} or not isinstance(record, Mapping):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact terminal outcome is invalid"
            )
        if (
            result.get("outcome") != record.get("outcome")
            or record.get("status") != record.get("outcome")
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact outcome is contradictory"
            )
        if record.get("claim_sha256") != claim.get("record_sha256"):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact claim binding is invalid"
            )
        evidence = dict(record)
        expected_hash = str(evidence.get("evidence_sha256") or "")
        payload = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
        if not expected_hash or canonical_sha256(payload) != expected_hash:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview completed evidence is tampered"
            )
        return evidence

    def _prepare_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        parent = self.path.parent.lstat()
        if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact parent is unsafe"
            )

    def _safe_regular_lstat(self) -> os.stat_result:
        try:
            result = self.path.lstat()
        except FileNotFoundError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is missing"
            ) from exc
        if stat.S_ISLNK(result.st_mode):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact path is a symlink"
            )
        if not stat.S_ISREG(result.st_mode):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is not a regular file"
            )
        return result

    def _read_rows(self) -> list[dict[str, Any]]:
        before = self._safe_regular_lstat()
        if before.st_size <= 0 or before.st_size > _MAX_ARTIFACT_BYTES:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact size is invalid"
            )
        try:
            fd = os.open(self.path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact cannot be read"
            ) from exc
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact identity changed"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_ARTIFACT_BYTES:
                    raise FuturesOrderPreviewArtifactError(
                        "futures Preview artifact is too large"
                    )
                chunks.append(chunk)
        finally:
            os.close(fd)
        raw = b"".join(chunks)
        if not raw.endswith(b"\n"):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact has an incomplete record"
            )
        try:
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact is tampered"
            ) from exc
        if not rows or len(rows) > 2 or any(not isinstance(row, dict) for row in rows):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact record count is invalid"
            )
        for row in rows:
            if row.get("schema_version") != _SCHEMA_VERSION:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact schema is invalid"
                )
            if row.get("record_sha256") != _record_sha256(row):
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview artifact is tampered"
                )
        return rows

    @staticmethod
    def _record(
        record_type: str,
        record: Mapping[str, Any],
        *,
        previous_record_sha256: str | None = None,
    ) -> dict[str, Any]:
        wrapped: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "record_type": record_type,
            "previous_record_sha256": previous_record_sha256,
            "record": _plain(record),
        }
        wrapped["record_sha256"] = _record_sha256(wrapped)
        return wrapped


def validate_futures_order_preview_predecessor(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_evidence_sha256: str,
    expected_device: int | None = None,
    expected_inode: int | None = None,
    expected_size: int | None = None,
    expected_mode: int = 0o400,
    expected_mtime_ns: int | None = None,
    expected_artifact_type: str = "futures_exact_no_live_preview_slice_2r1",
    expected_blocker: str = (
        "preflight_or_preview_blocked:ValueError:"
        "futures_preview_margin_setting_ambiguous"
    ),
    expected_predecessor_binding: Mapping[str, Any] | None = (
        FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING
    ),
) -> dict[str, Any]:
    """Read and bind one exact immutable terminal Preview predecessor."""

    predecessor = Path(path)
    try:
        before = predecessor.lstat()
    except FileNotFoundError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor is missing"
        ) from exc
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor is not a safe regular file"
        )
    if expected_device is not None and before.st_dev != expected_device:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor device changed"
        )
    if expected_inode is not None and before.st_ino != expected_inode:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor inode changed"
        )
    if expected_size is not None and before.st_size != expected_size:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor size changed"
        )
    if mode != expected_mode:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor mode changed"
        )
    if expected_mtime_ns is not None and before.st_mtime_ns != expected_mtime_ns:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor mtime changed"
        )
    if before.st_size <= 0 or before.st_size > _MAX_ARTIFACT_BYTES:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor size is invalid"
        )

    digest = hashlib.sha256()
    try:
        fd = os.open(predecessor, os.O_RDONLY | _NOFOLLOW)
    except OSError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor cannot be read"
        ) from exc
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview predecessor identity changed"
            )
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_ARTIFACT_BYTES:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview predecessor is too large"
                )
            digest.update(chunk)
    finally:
        os.close(fd)
    file_sha256 = digest.hexdigest()
    if not hmac.compare_digest(file_sha256, expected_file_sha256):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor file hash changed"
        )

    try:
        evidence = FuturesOrderPreviewArtifactStore(predecessor).read_completed()
    except FuturesOrderPreviewArtifactError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor terminal evidence is invalid"
        ) from exc
    evidence_sha256 = str(evidence.get("evidence_sha256") or "")
    attempts = _mapping(evidence.get("attempt_counters"))
    reads = _mapping(evidence.get("read_counters"))
    artifacts = _mapping(evidence.get("artifacts"))
    expected_zero_attempts = {
        "preview_order": 0,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    expected_reads = {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 1,
        "futures_positions": 1,
        "futures_margin_collateral": 1,
    }
    if (
        not hmac.compare_digest(evidence_sha256, expected_evidence_sha256)
        or evidence.get("artifact_type") != expected_artifact_type
        or evidence.get("status") != "blocked"
        or evidence.get("outcome") != "blocked"
        or evidence.get("blocker") != expected_blocker
        or attempts != expected_zero_attempts
        or reads != expected_reads
        or (
            expected_predecessor_binding is not None
            and evidence.get("predecessor_binding")
            != dict(expected_predecessor_binding)
        )
        or evidence.get("exchange_submission_attempt_count") != 0
        or evidence.get("submitted_notional_usdc") != "0"
        or evidence.get("executed_notional_usdc") != "0"
        or artifacts
        != {
            "execution_marker_created": False,
            "attempt_ledger_created": False,
            "runtime_created": False,
        }
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor terminal evidence is invalid"
        )

    after = predecessor.lstat()
    if (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mode,
        after.st_mtime_ns,
    ) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mode,
        before.st_mtime_ns,
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview predecessor changed during validation"
        )

    binding = {
        "artifact_name": predecessor.name,
        "file_sha256": file_sha256,
        "evidence_sha256": evidence_sha256,
        "device": str(before.st_dev),
        "inode": str(before.st_ino),
        "size_bytes": before.st_size,
        "mode": f"{mode:04o}",
        "mtime_ns": str(before.st_mtime_ns),
        "status": "blocked",
        "outcome": "blocked",
        "preview_order_attempt_count": 0,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "preservation": "immutable_no_modify_delete_or_reuse",
    }
    if expected_predecessor_binding is not None:
        binding["original_predecessor_binding"] = dict(
            expected_predecessor_binding
        )
    return binding


def validate_production_futures_order_preview_predecessor() -> dict[str, Any]:
    """Validate the exact R2 -> R1 -> original Slice 2 predecessor chain."""

    original_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_ORIGINAL_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_ORIGINAL_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_ORIGINAL_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_ORIGINAL_DEVICE,
        expected_inode=FUTURES_PREVIEW_ORIGINAL_INODE,
        expected_size=FUTURES_PREVIEW_ORIGINAL_SIZE,
        expected_mode=FUTURES_PREVIEW_ORIGINAL_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_ORIGINAL_MTIME_NS,
        expected_artifact_type="futures_exact_no_live_preview_slice_2",
        expected_blocker=(
            "preflight_or_preview_blocked:ValueError:"
            "futures_preview_product_status_blocked"
        ),
        expected_predecessor_binding=None,
    )
    if original_binding != FUTURES_PREVIEW_ORIGINAL_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview original predecessor binding changed"
        )

    r1_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R1_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R1_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R1_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R1_DEVICE,
        expected_inode=FUTURES_PREVIEW_R1_INODE,
        expected_size=FUTURES_PREVIEW_R1_SIZE,
        expected_mode=FUTURES_PREVIEW_R1_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R1_MTIME_NS,
        expected_predecessor_binding=original_binding,
    )
    if r1_binding != FUTURES_PREVIEW_R1_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R1 predecessor binding changed"
        )

    r2_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_PREDECESSOR_DEVICE,
        expected_inode=FUTURES_PREVIEW_PREDECESSOR_INODE,
        expected_size=FUTURES_PREVIEW_PREDECESSOR_SIZE,
        expected_mode=FUTURES_PREVIEW_PREDECESSOR_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_PREDECESSOR_MTIME_NS,
        expected_artifact_type="futures_exact_no_live_preview_slice_2r2",
        expected_blocker="preflight_or_preview_blocked:ValueError",
        expected_predecessor_binding=r1_binding,
    )
    if r2_binding != FUTURES_PREVIEW_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R2 predecessor binding changed"
        )
    return r2_binding


def validate_production_futures_order_preview_r3_predecessor() -> dict[str, Any]:
    """Validate immutable R3 plus its complete R2/R1/original chain."""

    r2_binding = validate_production_futures_order_preview_predecessor()
    r3_binding = validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_R3_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_R3_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_R3_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_R3_DEVICE,
        expected_inode=FUTURES_PREVIEW_R3_INODE,
        expected_size=FUTURES_PREVIEW_R3_SIZE,
        expected_mode=FUTURES_PREVIEW_R3_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_R3_MTIME_NS,
        expected_artifact_type=_ARTIFACT_TYPE,
        expected_blocker="preflight_or_preview_stage_blocked",
        expected_predecessor_binding=r2_binding,
    )
    if r3_binding != FUTURES_PREVIEW_R3_PREDECESSOR_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R3 predecessor binding changed"
        )
    return r3_binding


class FuturesOrderPreviewProducer:
    """Consume one fixed authorization to produce Preview-only evidence."""

    def __init__(
        self,
        *,
        rest_client: Any,
        store: FuturesOrderPreviewArtifactStore,
        predecessor_binding: Mapping[str, Any],
        predecessor_validator: Callable[[], Mapping[str, Any]],
        artifact_type: str = _ARTIFACT_TYPE,
        now: Callable[[], datetime] | None = None,
        correlation_id_factory: Callable[[], str] | None = None,
        idempotency_key_factory: Callable[[], str] | None = None,
    ) -> None:
        if artifact_type not in {_ARTIFACT_TYPE, _R4_ARTIFACT_TYPE}:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact generation is invalid"
            )
        expected_predecessor_name = (
            "futures_exact_no_live_preview_slice_2r2.jsonl"
            if artifact_type == _ARTIFACT_TYPE
            else "futures_exact_no_live_preview_slice_2r3.jsonl"
        )
        if predecessor_binding.get("artifact_name") != expected_predecessor_name:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview predecessor generation is invalid"
            )
        self.rest_client = rest_client
        self.store = store
        self.artifact_type = artifact_type
        self.predecessor_binding = dict(predecessor_binding)
        self.predecessor_validator = predecessor_validator
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.correlation_id_factory = correlation_id_factory or (lambda: str(uuid4()))
        self.idempotency_key_factory = idempotency_key_factory or (lambda: str(uuid4()))

    def build_claim(self) -> dict[str, Any]:
        """Build the fixed claim without calling Coinbase."""

        correlation_id = self.correlation_id_factory()
        idempotency_key = self.idempotency_key_factory()
        if (
            correlation_id in _CONSUMED_PREVIEW_IDENTIFIERS
            or idempotency_key in _CONSUMED_PREVIEW_IDENTIFIERS
            or correlation_id == idempotency_key
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview identifiers are not fresh"
            )
        return {
            "artifact_type": self.artifact_type,
            "claim_status": "reserved",
            "predecessor_binding": dict(self.predecessor_binding),
            "reserved_at": _timestamp(self.now()),
            "actor_id": FUTURES_PREVIEW_ACTOR_ID,
            "roles": [FUTURES_PREVIEW_ROLE],
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
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
            "allowed_coinbase_methods": [
                "get_api_key_permissions",
                "list_portfolios",
                "get_product_dict",
                "get_best_bid_ask",
                "get_futures_positions",
                "get_futures_margin_collateral_snapshot",
                "preview_order",
            ],
            "preview_order_attempt_max": 1,
            "retry_attempt_max": 0,
            "fallback_attempt_max": 0,
            "create_order_attempt_max": 0,
            "cancel_order_attempt_max": 0,
            "close_position_attempt_max": 0,
            "reduce_position_attempt_max": 0,
            "marker_created": False,
            "ledger_created": False,
            "runtime_created": False,
        }

    def run(self) -> dict[str, Any]:
        """Reserve once, preflight, and make at most one Preview call."""

        observed_predecessor = dict(self.predecessor_validator())
        if observed_predecessor != self.predecessor_binding:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview predecessor binding changed"
            )
        claim = self.build_claim()
        claim_sha256 = self.store.reserve(claim)
        counters = _zero_attempt_counters()
        read_counters = _zero_read_counters()
        terminal_context: dict[str, Any] = {}
        passed_pre_preview_stages: list[str] = []
        try:
            try:
                revalidated_predecessor = dict(self.predecessor_validator())
            except FuturesOrderPreviewArtifactError as exc:
                raise ValueError(
                    f"futures_preview_predecessor_validation_blocked:{exc}"
                ) from exc
            if revalidated_predecessor != self.predecessor_binding:
                raise ValueError(
                    "futures_preview_predecessor_binding_changed_after_claim"
                )
            read_counters["api_key_permissions"] = 1
            permissions = _plain(self.rest_client.get_api_key_permissions())
            read_counters["portfolio_catalog"] = 1
            portfolios = _plain(self.rest_client.list_portfolios())
            binding = evaluate_futures_default_portfolio_binding(
                permissions=permissions,
                portfolios=portfolios,
                observed_at=_timestamp(self.now()),
                permissions_read=True,
                portfolio_catalog_read=True,
            )
            if (
                not binding.read_ready
                or binding.can_view is not True
                or binding.can_trade is not True
            ):
                raise ValueError(
                    binding.blocker
                    or "futures_default_portfolio_trade_permission_missing"
                )
            read_counters["product"] = 1
            product = _plain(
                self.rest_client.get_product_dict(FUTURES_PREVIEW_PRODUCT_ID)
            )
            read_counters["best_bid_ask"] = 1
            book = _plain(
                self.rest_client.get_best_bid_ask(
                    product_ids=[FUTURES_PREVIEW_PRODUCT_ID]
                )
            )
            read_counters["futures_positions"] = 1
            positions = _plain(self.rest_client.get_futures_positions())
            read_counters["futures_margin_collateral"] = 1
            margin_collateral_observed = False
            try:
                margin_collateral = _plain(
                    self.rest_client.get_futures_margin_collateral_snapshot()
                )
                margin_collateral_observed = True
                terminal_context.update(
                    _margin_setting_terminal_context(margin_collateral)
                )
                available_margin = validate_margin_collateral_evidence(
                    margin_collateral
                )
            except Exception as exc:
                if (
                    self.artifact_type == _R4_ARTIFACT_TYPE
                    and margin_collateral_observed
                    and type(exc) is ValueError
                    and exc.args
                    == ("futures_preview_margin_windows_ambiguous",)
                ):
                    terminal_context.update(
                        _margin_windows_terminal_context(margin_collateral)
                    )
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="remaining_margin_validation",
                        exc=exc,
                    )
                )
                raise
            passed_pre_preview_stages.append("remaining_margin_validation")
            try:
                observed_at = self.now()
                candidate = build_futures_order_preview_candidate(
                    product=product,
                    book=book,
                    positions=positions,
                    observed_at=observed_at,
                )
            except Exception as exc:
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="candidate_construction",
                        exc=exc,
                    )
                )
                raise
            passed_pre_preview_stages.append("candidate_construction")
            try:
                preview_request = _preview_request(candidate)
            except Exception as exc:
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="preview_request_construction",
                        exc=exc,
                    )
                )
                raise
            passed_pre_preview_stages.append("preview_request_construction")
            try:
                attempt_context = _terminal_attempt_context(
                    binding=binding.to_dict(),
                    permissions=permissions,
                    portfolios=portfolios,
                    product=product,
                    book=book,
                    positions=positions,
                    margin_collateral=margin_collateral,
                    candidate=candidate,
                    preview_request=preview_request,
                )
                try:
                    pre_preview_predecessor = dict(
                        self.predecessor_validator()
                    )
                except FuturesOrderPreviewArtifactError as exc:
                    raise ValueError(
                        "futures_preview_predecessor_pre_preview_blocked"
                    ) from exc
                if pre_preview_predecessor != self.predecessor_binding:
                    raise ValueError(
                        "futures_preview_predecessor_binding_changed_pre_preview"
                    )
            except Exception as exc:
                terminal_context.update(
                    _pre_preview_stage_failure_context(
                        passed_stages=passed_pre_preview_stages,
                        blocked_stage="terminal_context_sanitization",
                        exc=exc,
                    )
                )
                raise
            terminal_context = attempt_context
            passed_pre_preview_stages.append("terminal_context_sanitization")
            counters["preview_order"] = 1
            try:
                preview_response = _plain(
                    self.rest_client.preview_order(**preview_request)
                )
            except Exception as exc:
                transition_blocker = self._terminal_predecessor_blocker()
                blocker = f"preview_order_unknown:{type(exc).__name__}"
                if transition_blocker is not None:
                    blocker = f"{blocker};{transition_blocker}"
                result = _terminal_failure_record(
                    claim=claim,
                    claim_sha256=claim_sha256,
                    counters=counters,
                    read_counters=read_counters,
                    outcome="unknown",
                    blocker=blocker,
                    context=terminal_context,
                )
                self.store.append_result(result)
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview outcome is unknown; attempt consumed"
                ) from exc
            normalized_preview = validate_preview_response(preview_response)
            terminal_context["preview_response"] = normalized_preview
            terminal_context["preview_response_sha256"] = canonical_sha256(
                normalized_preview
            )
            normalized_preview = validate_preview_against_candidate(
                normalized_preview,
                candidate,
            )
            terminal_context["preview_response"] = normalized_preview
            terminal_context["preview_response_sha256"] = canonical_sha256(
                normalized_preview
            )
            preview_margin = _decimal(
                normalized_preview["order_margin_total"],
                "order_margin_total",
            )
            if preview_margin > available_margin:
                raise ValueError("futures_preview_available_margin_insufficient")
            seal_ready_plan = _seal_ready_plan(
                claim=claim,
                binding=binding.to_dict(),
                candidate=candidate,
                preview_request=preview_request,
                preview_response=normalized_preview,
                permissions=permissions,
                portfolios=portfolios,
                product=product,
                book=book,
                positions=positions,
                margin_collateral=margin_collateral,
            )
            evidence = _accepted_evidence(
                claim=claim,
                claim_sha256=claim_sha256,
                counters=counters,
                read_counters=read_counters,
                binding=binding.to_dict(),
                permissions=permissions,
                portfolios=portfolios,
                product=product,
                book=book,
                positions=positions,
                margin_collateral=margin_collateral,
                candidate=candidate,
                preview_request=preview_request,
                preview_response=normalized_preview,
                seal_ready_plan=seal_ready_plan,
                completed_at=self.now(),
            )
            transition_blocker = self._terminal_predecessor_blocker()
            if transition_blocker is not None:
                raise ValueError(transition_blocker)
            self.store.append_result(evidence)
            return self.store.read_completed()
        except FuturesOrderPreviewArtifactError:
            raise
        except Exception as exc:
            transition_blocker = self._terminal_predecessor_blocker()
            stage_failure = "pre_preview_stage_evidence" in terminal_context
            blocker = (
                "preflight_or_preview_stage_blocked"
                if stage_failure
                else _redacted_preflight_blocker(exc)
            )
            if (
                transition_blocker is not None
                and not stage_failure
                and transition_blocker not in blocker
            ):
                blocker = f"{blocker};{transition_blocker}"
            result = _terminal_failure_record(
                claim=claim,
                claim_sha256=claim_sha256,
                counters=counters,
                read_counters=read_counters,
                outcome="blocked",
                blocker=blocker,
                context=terminal_context,
            )
            self.store.append_result(result)
            raise FuturesOrderPreviewArtifactError(
                "futures Preview preflight blocked; attempt consumed"
            ) from exc

    def _terminal_predecessor_blocker(self) -> str | None:
        """Return a redacted transition blocker immediately before append."""

        try:
            observed = dict(self.predecessor_validator())
        except Exception as exc:
            return (
                "futures_preview_predecessor_terminal_validation_blocked:"
                f"{type(exc).__name__}"
            )
        if observed != self.predecessor_binding:
            return "futures_preview_predecessor_terminal_binding_changed"
        return None


def build_futures_order_preview_candidate(
    *,
    product: Mapping[str, Any],
    book: Mapping[str, Any],
    positions: Any,
    observed_at: datetime,
) -> dict[str, str]:
    """Build the fixed one-contract resting AVAX candidate or fail closed."""

    if str(product.get("product_id") or "") != FUTURES_PREVIEW_PRODUCT_ID:
        raise ValueError("futures_preview_product_identity_blocked")
    if str(product.get("display_name") or "").strip() != "AVAX PERP":
        raise ValueError("futures_preview_avp_display_name_blocked")
    if str(product.get("product_type") or "").upper() != "FUTURE":
        raise ValueError("futures_preview_product_type_blocked")
    if "status" not in product or product.get("status") != "":
        raise ValueError("futures_preview_product_status_blocked")
    if any(
        product.get(field) is not False
        for field in ("trading_disabled", "view_only", "cancel_only")
    ):
        raise ValueError("futures_preview_product_trading_blocked")

    details = _mapping(product.get("future_product_details"))
    exact_perp_style_identity = {
        "contract_code": "AVP",
        "group_description": "Avalanche Perp Futures",
        "group_short_description": "Avalanche Perp",
        "venue": "cde",
        "risk_managed_by": "MANAGED_BY_FCM",
        "contract_expiry": "2030-12-20T16:00:00Z",
        "contract_expiry_type": "EXPIRING",
    }
    if any(
        details.get(field) != expected
        for field, expected in exact_perp_style_identity.items()
    ):
        raise ValueError("futures_preview_avp_perp_style_identity_blocked")
    contract_expiry_type = str(
        details.get("contract_expiry_type") or ""
    ).strip().upper()
    contract_size = _positive_decimal(details.get("contract_size"), "contract_size")
    if contract_size != Decimal("10"):
        raise ValueError("futures_preview_avp_contract_size_blocked")
    product_price = _positive_decimal(product.get("price"), "product_price")
    price_increment = _positive_decimal(product.get("price_increment"), "price_increment")
    base_increment = _positive_decimal(product.get("base_increment"), "base_increment")
    base_min_size = _positive_decimal(product.get("base_min_size"), "base_min_size")
    if (
        FUTURES_PREVIEW_CONTRACT_COUNT < base_min_size
        or FUTURES_PREVIEW_CONTRACT_COUNT % base_increment != 0
    ):
        raise ValueError("futures_preview_one_contract_rule_blocked")

    pricebook = _exact_pricebook(book)
    _validate_market_freshness(pricebook, observed_at)
    best_bid = _top_price(pricebook, "bids")
    best_ask = _top_price(pricebook, "asks")
    if best_bid >= best_ask:
        raise ValueError("futures_preview_crossed_or_ambiguous_book")
    if best_bid % price_increment != 0:
        raise ValueError("futures_preview_best_bid_tick_misaligned")
    limit_price = best_bid - price_increment
    if limit_price <= 0 or limit_price % price_increment != 0:
        raise ValueError("futures_preview_limit_tick_blocked")
    if _position_contracts(positions, FUTURES_PREVIEW_PRODUCT_ID) != 0:
        raise ValueError("futures_preview_existing_product_exposure_blocked")

    reference_price = max(product_price, best_ask)
    opening = reference_price * contract_size * FUTURES_PREVIEW_CONTRACT_COUNT
    exposure = opening
    buffered_close = exposure * FUTURES_PREVIEW_CLOSE_BUFFER
    turnover = opening + buffered_close
    if opening >= FUTURES_PREVIEW_OPENING_CAP_USDC:
        raise ValueError("futures_preview_opening_cap_blocked")
    if exposure >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_exposure_cap_blocked")
    if buffered_close >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_buffered_close_cap_blocked")
    if turnover >= FUTURES_PREVIEW_TURNOVER_CAP_USDC:
        raise ValueError("futures_preview_turnover_cap_blocked")

    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "product_classification": "PERP_STYLE_FUTURE",
        "contract_code": "AVP",
        "contract_expiry": "2030-12-20T16:00:00Z",
        "contract_expiry_type": contract_expiry_type,
        "venue": "cde",
        "risk_managed_by": "MANAGED_BY_FCM",
        "contract_size": _decimal_text(contract_size),
        "product_price": _decimal_text(product_price),
        "reference_price": _decimal_text(reference_price),
        "reference_price_source": "max_product_price_and_fresh_best_ask",
        "price_increment": _decimal_text(price_increment),
        "best_bid": _decimal_text(best_bid),
        "best_ask": _decimal_text(best_ask),
        "limit_price": _decimal_text(limit_price),
        "opening_reference_notional_usdc": _notional_text(opening),
        "maximum_exposure_reference_notional_usdc": _notional_text(exposure),
        "observed_concurrent_exposure_usdc": _notional_text(exposure),
        "buffered_close_reference_notional_usdc": _notional_text(buffered_close),
        "branch_turnover_reference_notional_usdc": _notional_text(turnover),
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "close_buffer_multiplier": "1.20",
        "observed_at": _timestamp(observed_at),
    }


def validate_preview_response(value: Any) -> dict[str, Any]:
    """Return exact allowlisted fee, margin, and liquidation evidence."""

    response = _mapping(value)
    if not response:
        raise ValueError("futures_preview_response_missing")
    if not isinstance(response.get("errs"), list):
        raise ValueError("futures_preview_response_errors_ambiguous")
    if response["errs"]:
        raise ValueError("futures_preview_response_errors_present")
    if not isinstance(response.get("warning"), list):
        raise ValueError("futures_preview_response_warning_ambiguous")
    if response["warning"]:
        raise ValueError("futures_preview_response_warning_present")
    for field in (
        "preview_id",
        "order_total",
        "commission_total",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "order_margin_total",
    ):
        if not _nonempty(response.get(field)):
            raise ValueError(f"futures_preview_response_{field}_missing")
    preview_id = response["preview_id"]
    if (
        not isinstance(preview_id, str)
        or preview_id != preview_id.strip()
        or not preview_id.isprintable()
        or len(preview_id) > 256
    ):
        raise ValueError("futures_preview_response_preview_id_invalid")
    decimals: dict[str, Decimal] = {}
    for field in (
        "order_total",
        "commission_total",
        "quote_size",
        "base_size",
        "best_bid",
        "best_ask",
        "order_margin_total",
    ):
        decimal = _decimal(response[field], field)
        decimals[field] = decimal
        if not decimal.is_finite():
            raise ValueError(f"futures_preview_response_{field}_not_finite")
        if field == "commission_total":
            if decimal < 0:
                raise ValueError(f"futures_preview_response_{field}_negative")
        elif decimal <= 0:
            raise ValueError(f"futures_preview_response_{field}_not_positive")
    legacy_liquidation_ready = all(
        _nonempty(response.get(field))
        for field in (
            "current_liquidation_buffer",
            "projected_liquidation_buffer",
        )
    )
    replacement_liquidation_ready = (
        bool(_mapping(response.get("margin_ratio_data")))
        and _nonempty(response.get("predicted_liquidation_price"))
    )
    sanitized: dict[str, Any] = {
        "preview_id": preview_id,
        "errs": [],
        "warning": [],
        **{
            field: _decimal_text(decimals[field])
            for field in (
                "order_total",
                "commission_total",
                "quote_size",
                "base_size",
                "best_bid",
                "best_ask",
                "order_margin_total",
            )
        },
    }
    if legacy_liquidation_ready:
        for field in (
            "current_liquidation_buffer",
            "projected_liquidation_buffer",
        ):
            decimal = _decimal(response[field], field)
            if not decimal.is_finite() or decimal < 0:
                raise ValueError(
                    f"futures_preview_liquidation_{field}_not_finite_or_negative"
                )
            sanitized[field] = _decimal_text(decimal)
        sanitized["liquidation_evidence_source"] = (
            "current_and_projected_liquidation_buffer"
        )
    elif replacement_liquidation_ready:
        margin_ratio_data = _mapping(response["margin_ratio_data"])
        sanitized_margin_ratio: dict[str, str] = {}
        for field in ("current_margin_ratio", "projected_margin_ratio"):
            decimal = _decimal(margin_ratio_data.get(field), field)
            if not decimal.is_finite() or decimal < 0:
                raise ValueError(
                    f"futures_preview_margin_ratio_{field}_not_finite_or_negative"
                )
            sanitized_margin_ratio[field] = _decimal_text(decimal)
        predicted_liquidation_price = _decimal(
            response["predicted_liquidation_price"],
            "predicted_liquidation_price",
        )
        if (
            not predicted_liquidation_price.is_finite()
            or predicted_liquidation_price <= 0
        ):
            raise ValueError(
                "futures_preview_predicted_liquidation_price_not_finite_or_positive"
            )
        sanitized["margin_ratio_data"] = sanitized_margin_ratio
        sanitized["predicted_liquidation_price"] = _decimal_text(
            predicted_liquidation_price
        )
        sanitized["liquidation_evidence_source"] = (
            "margin_ratio_data_and_predicted_liquidation_price"
        )
    else:
        raise ValueError("futures_preview_response_liquidation_evidence_incomplete")
    return sanitized


def validate_margin_collateral_evidence(value: Any) -> Decimal:
    """Return authoritative available US CFM margin or fail closed."""

    evidence = _mapping(value)
    if (
        evidence.get("status") != "ready"
        or evidence.get("account_family") != "coinbase_futures_us_cfm"
        or evidence.get("source") != "backend_rest_client"
        or evidence.get("intx_applicability") != "not_applicable_us_account"
        or not isinstance(evidence.get("errors"), list)
        or bool(evidence["errors"])
    ):
        raise ValueError("futures_preview_margin_collateral_ambiguous")
    summary = _mapping(evidence.get("balance_summary"))
    if _mapping(evidence.get("source_read_attempts")) != (
        FUTURES_PREVIEW_EXPECTED_MARGIN_SOURCE_READS
    ):
        raise ValueError("futures_preview_margin_source_reads_ambiguous")
    available = _usd_money_value(
        summary.get("available_margin"),
        "available_margin",
    )
    _usd_money_value(summary.get("total_usd_balance"), "total_usd_balance")
    _usd_money_value(summary.get("cfm_usd_balance"), "cfm_usd_balance")
    _usd_money_value(summary.get("futures_buying_power"), "futures_buying_power")
    _usd_money_value(summary.get("initial_margin"), "initial_margin")
    _usd_money_value(
        summary.get("liquidation_threshold"),
        "liquidation_threshold",
    )
    measure = _mapping(summary.get("intraday_margin_window_measure"))
    if (
        measure.get("margin_window_type")
        not in FUTURES_PREVIEW_OPERATIONAL_FCM_MARGIN_WINDOW_TYPES
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
    if setting not in FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS:
        raise ValueError("futures_preview_margin_setting_unspecified")
    margin_windows_diagnostic = _classify_margin_windows(evidence)
    failing_row_index = margin_windows_diagnostic["failing_row_index"]
    if (
        margin_windows_diagnostic["classification"] != "ready"
        and failing_row_index is None
        and margin_windows_diagnostic["classification"]
        != "expected_profile_set_incomplete"
    ):
        raise ValueError("futures_preview_margin_windows_ambiguous")
    windows = evidence.get("current_margin_windows", [])
    for index, item in enumerate(windows):
        if failing_row_index == index:
            raise ValueError("futures_preview_margin_windows_ambiguous")
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
    if margin_windows_diagnostic["classification"] != "ready":
        raise ValueError("futures_preview_margin_windows_ambiguous")
    if (
        not isinstance(evidence.get("futures_sweeps"), list)
        or bool(evidence["futures_sweeps"])
    ):
        raise ValueError("futures_preview_margin_sweeps_ambiguous")
    if available <= 0:
        raise ValueError("futures_preview_available_margin_not_positive")
    return available


def validate_preview_against_candidate(
    preview: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind authoritative Preview size/notional back to the fixed caps."""

    response = dict(preview)
    base_size = _positive_decimal(response.get("base_size"), "preview_base_size")
    if base_size != FUTURES_PREVIEW_CONTRACT_COUNT:
        raise ValueError("futures_preview_base_size_candidate_mismatch")
    order_total = _positive_decimal(
        response.get("order_total"),
        "preview_order_total",
    )
    quote_size = _positive_decimal(
        response.get("quote_size"),
        "preview_quote_size",
    )
    commission = _decimal(
        response.get("commission_total"),
        "preview_commission_total",
    )
    if not commission.is_finite() or commission < 0:
        raise ValueError("futures_preview_commission_total_invalid")
    preview_bid = _positive_decimal(response.get("best_bid"), "preview_best_bid")
    preview_ask = _positive_decimal(response.get("best_ask"), "preview_best_ask")
    if preview_bid >= preview_ask:
        raise ValueError("futures_preview_response_book_ambiguous")

    contract_size = _positive_decimal(
        candidate.get("contract_size"),
        "candidate_contract_size",
    )
    preview_market_reference = (
        preview_ask * contract_size * FUTURES_PREVIEW_CONTRACT_COUNT
    )
    candidate_opening = _positive_decimal(
        candidate.get("opening_reference_notional_usdc"),
        "candidate_opening_reference_notional",
    )
    authoritative_opening = max(
        candidate_opening,
        preview_market_reference,
        order_total + commission,
        quote_size + commission,
    )
    maximum_exposure = authoritative_opening
    buffered_close = maximum_exposure * FUTURES_PREVIEW_CLOSE_BUFFER
    turnover = authoritative_opening + buffered_close
    if authoritative_opening >= FUTURES_PREVIEW_OPENING_CAP_USDC:
        raise ValueError("futures_preview_response_opening_cap_blocked")
    if maximum_exposure >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_response_exposure_cap_blocked")
    if buffered_close >= FUTURES_PREVIEW_EXPOSURE_CAP_USDC:
        raise ValueError("futures_preview_response_buffered_close_cap_blocked")
    if turnover >= FUTURES_PREVIEW_TURNOVER_CAP_USDC:
        raise ValueError("futures_preview_response_turnover_cap_blocked")
    response["candidate_binding"] = {
        "status": "matched",
        "contract_count": "1",
        "authoritative_opening_reference_notional_usdc": _notional_text(
            authoritative_opening
        ),
        "maximum_exposure_reference_notional_usdc": _notional_text(
            maximum_exposure
        ),
        "buffered_close_reference_notional_usdc": _notional_text(
            buffered_close
        ),
        "branch_turnover_reference_notional_usdc": _notional_text(turnover),
        "reference_rule": (
            "max_candidate_reference_preview_ask_contract_notional_"
            "order_total_plus_fee_quote_size_plus_fee"
        ),
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "comparison": "strictly_less_than",
    }
    return response


def _accepted_evidence(
    *,
    claim: Mapping[str, Any],
    claim_sha256: str,
    counters: Mapping[str, int],
    read_counters: Mapping[str, int],
    binding: Mapping[str, Any],
    permissions: Any,
    portfolios: Any,
    product: Mapping[str, Any],
    book: Mapping[str, Any],
    positions: Any,
    margin_collateral: Mapping[str, Any],
    candidate: Mapping[str, Any],
    preview_request: Mapping[str, Any],
    preview_response: Mapping[str, Any],
    seal_ready_plan: Mapping[str, Any],
    completed_at: datetime,
) -> dict[str, Any]:
    sanitized_permissions = _sanitized_permission_evidence(binding)
    sanitized_portfolio = _sanitized_portfolio_catalog_evidence(binding)
    sanitized_positions = _sanitized_position_evidence(positions)
    sanitized_margin = _sanitized_margin_collateral_evidence(margin_collateral)
    evidence: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "type": "admin_futures_order_preview",
        "artifact_type": claim["artifact_type"],
        "status": "accepted",
        "outcome": "accepted",
        "predecessor_binding": dict(claim["predecessor_binding"]),
        "reserved_at": claim["reserved_at"],
        "completed_at": _timestamp(completed_at),
        "claim_sha256": claim_sha256,
        "actor_id": claim["actor_id"],
        "roles": list(claim["roles"]),
        "correlation_id": claim["correlation_id"],
        "idempotency_key": claim["idempotency_key"],
        "profile_label": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id": binding.get("observed_portfolio_id"),
        "portfolio_binding": dict(binding),
        "permission_evidence": sanitized_permissions,
        "permission_evidence_sha256": canonical_sha256(sanitized_permissions),
        "portfolio_catalog_evidence": sanitized_portfolio,
        "portfolio_catalog_sha256": canonical_sha256(sanitized_portfolio),
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "product_evidence": _plain(product),
        "product_evidence_sha256": canonical_sha256(product),
        "market_evidence": _plain(book),
        "market_evidence_sha256": canonical_sha256(book),
        "position_evidence": sanitized_positions,
        "position_evidence_sha256": canonical_sha256(sanitized_positions),
        "margin_collateral_evidence": sanitized_margin,
        "margin_collateral_evidence_sha256": canonical_sha256(sanitized_margin),
        **_margin_setting_terminal_context(margin_collateral),
        "candidate": dict(candidate),
        "candidate_sha256": canonical_sha256(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
        "preview_response": dict(preview_response),
        "preview_response_sha256": canonical_sha256(preview_response),
        "seal_ready_plan": dict(seal_ready_plan),
        "seal_ready_plan_sha256": canonical_sha256(seal_ready_plan),
        "attempt_counters": dict(counters),
        "read_counters": dict(read_counters),
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_execution": "not_run",
        "live_coinbase_execution": "not_run",
        "live_coinbase_read_ran": True,
        "exchange_submission_attempt_count": 0,
        "read_only": True,
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
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def _terminal_failure_record(
    *,
    claim: Mapping[str, Any],
    claim_sha256: str,
    counters: Mapping[str, int],
    read_counters: Mapping[str, int],
    outcome: str,
    blocker: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "type": "admin_futures_order_preview",
        "artifact_type": claim["artifact_type"],
        "status": outcome,
        "outcome": outcome,
        "predecessor_binding": dict(claim["predecessor_binding"]),
        "reserved_at": claim["reserved_at"],
        "completed_at": _timestamp(datetime.now(timezone.utc)),
        "claim_sha256": claim_sha256,
        "actor_id": claim["actor_id"],
        "roles": list(claim["roles"]),
        "correlation_id": claim["correlation_id"],
        "idempotency_key": claim["idempotency_key"],
        "profile_label": "Default",
        "portfolio_type": "DEFAULT",
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "attempt_counters": dict(counters),
        "read_counters": dict(read_counters),
        "blocker": blocker,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_execution": "not_run",
        "live_coinbase_execution": "not_run",
        "live_coinbase_read_ran": any(read_counters.values()),
        "exchange_submission_attempt_count": 0,
        "read_only": True,
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
    if context:
        normalized_context = {
            key: _plain(context[key])
            for key in _TERMINAL_FAILURE_CONTEXT_ALLOWED_KEYS
            if key in context
        }
        evidence.update(normalized_context)
        stage_evidence = (
            _plain(context["pre_preview_stage_evidence"])
            if "pre_preview_stage_evidence" in context
            else None
        )
        stage_evidence_sha256 = (
            _plain(context["pre_preview_stage_evidence_sha256"])
            if "pre_preview_stage_evidence_sha256" in context
            else None
        )
        if stage_evidence is not None or stage_evidence_sha256 is not None:
            evidence["pre_preview_stage_evidence"] = stage_evidence
            evidence["pre_preview_stage_evidence_sha256"] = (
                stage_evidence_sha256
            )
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def _terminal_attempt_context(
    *,
    binding: Mapping[str, Any],
    permissions: Any,
    portfolios: Any,
    product: Any,
    book: Any,
    positions: Any,
    margin_collateral: Any,
    candidate: Mapping[str, Any],
    preview_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the exact preflight and payload for any post-attempt terminal state."""

    sanitized_permissions = _sanitized_permission_evidence(binding)
    sanitized_portfolio = _sanitized_portfolio_catalog_evidence(binding)
    sanitized_positions = _sanitized_position_evidence(positions)
    sanitized_margin = _sanitized_margin_collateral_evidence(margin_collateral)
    return {
        "portfolio_id": binding.get("observed_portfolio_id"),
        "portfolio_binding": dict(binding),
        "permission_evidence": sanitized_permissions,
        "permission_evidence_sha256": canonical_sha256(sanitized_permissions),
        "portfolio_catalog_evidence": sanitized_portfolio,
        "portfolio_catalog_sha256": canonical_sha256(sanitized_portfolio),
        "product_evidence": _plain(product),
        "product_evidence_sha256": canonical_sha256(product),
        "market_evidence": _plain(book),
        "market_evidence_sha256": canonical_sha256(book),
        "position_evidence": sanitized_positions,
        "position_evidence_sha256": canonical_sha256(sanitized_positions),
        "margin_collateral_evidence": sanitized_margin,
        "margin_collateral_evidence_sha256": canonical_sha256(sanitized_margin),
        **_margin_setting_terminal_context(margin_collateral),
        "candidate": dict(candidate),
        "candidate_sha256": canonical_sha256(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
    }


def _sanitized_permission_evidence(
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "portfolio_id": binding.get("observed_portfolio_id"),
        "portfolio_type": binding.get("observed_portfolio_type"),
        "can_view": binding.get("can_view"),
        "can_trade": binding.get("can_trade"),
        "selection_authority": binding.get("selection_authority"),
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_portfolio_catalog_evidence(
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "selected_portfolio_id": binding.get("observed_portfolio_id"),
        "selected_portfolio_label": binding.get("observed_portfolio_label"),
        "selected_portfolio_type": binding.get("observed_portfolio_type"),
        "exact_match_count": 1,
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_position_evidence(positions: Any) -> dict[str, Any]:
    contracts = _position_contracts(positions, FUTURES_PREVIEW_PRODUCT_ID)
    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "observed_contract_count": _decimal_text(contracts),
        "sanitized": True,
        "raw_response_included": False,
    }


def _sanitized_margin_collateral_evidence(value: Any) -> dict[str, Any]:
    evidence = _mapping(value)
    summary = _mapping(evidence.get("balance_summary"))
    measure = _mapping(summary.get("intraday_margin_window_measure"))
    setting = _mapping(evidence.get("intraday_margin_setting"))
    windows: list[dict[str, Any]] = []
    for item in evidence.get("current_margin_windows", []):
        window = _mapping(item)
        margin_window = _mapping(window.get("margin_window"))
        windows.append(
            {
                "profile": window.get("profile"),
                "margin_window_type": margin_window.get("margin_window_type"),
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
            _mapping(evidence.get("source_read_attempts"))
        ),
        "available_margin_usdc": _decimal_text(
            _usd_money_value(summary.get("available_margin"), "available_margin")
        ),
        "intraday_margin_window_measure": {
            "margin_window_type": measure.get("margin_window_type"),
            "maintenance_margin_usdc": _decimal_text(
                _decimal(measure.get("maintenance_margin"), "maintenance_margin")
            ),
            "liquidation_buffer_usdc": _decimal_text(
                _decimal(measure.get("liquidation_buffer"), "liquidation_buffer")
            ),
        },
        "intraday_margin_setting": {"setting": setting.get("setting")},
        "current_margin_windows": windows,
        "futures_sweep_count": len(evidence.get("futures_sweeps", [])),
        "sanitized": True,
        "raw_response_included": False,
    }


def _margin_setting_terminal_context(
    margin_collateral: Any,
) -> dict[str, Any]:
    """Return a secret-minimized margin-setting diagnostic."""

    snapshot = _plain(margin_collateral)
    snapshot_mapping = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    container_present = "intraday_margin_setting" in snapshot_mapping
    raw_setting_evidence = snapshot_mapping.get("intraday_margin_setting")
    container_type = _diagnostic_value_type(
        raw_setting_evidence,
        present=container_present,
    )
    setting_evidence = (
        dict(_plain(raw_setting_evidence))
        if isinstance(raw_setting_evidence, Mapping)
        else {}
    )
    setting_present = "setting" in setting_evidence
    setting = setting_evidence.get("setting") if setting_present else None
    value_type = _diagnostic_value_type(setting, present=setting_present)
    token_is_well_formed = (
        isinstance(setting, str)
        and setting == setting.strip()
        and _SAFE_MARGIN_SETTING_TOKEN.fullmatch(setting) is not None
    )
    safe_setting = (
        setting
        if isinstance(setting, str)
        and setting in FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS
        else None
    )
    allowlist_match = (
        isinstance(setting, str)
        and setting in FUTURES_PREVIEW_DOCUMENTED_MARGIN_SETTINGS
    )
    operationally_resolved = (
        isinstance(setting, str)
        and setting in FUTURES_PREVIEW_OPERATIONAL_MARGIN_SETTINGS
    )
    if token_is_well_formed:
        token_form = "safe_enum_token"
        classification = (
            "recognized_string"
            if allowlist_match
            else "unrecognized_string"
        )
    elif isinstance(setting, str):
        token_form = "malformed_string"
        classification = "malformed_string"
    elif not container_present:
        token_form = "not_applicable"
        classification = "missing_container"
    elif not isinstance(raw_setting_evidence, Mapping):
        token_form = "not_applicable"
        classification = "non_mapping_container"
    elif not setting_present:
        token_form = "not_applicable"
        classification = "missing_field"
    elif setting is None:
        token_form = "not_applicable"
        classification = "null_value"
    else:
        token_form = "not_applicable"
        classification = "non_string_value"
    diagnostic = {
        "source": "backend_rest_client.get_intraday_margin_setting",
        "stage": "margin_collateral_validation",
        "field_path": "intraday_margin_setting.setting",
        "container_present": container_present,
        "container_type": container_type,
        "field_present": setting_present,
        "value_type": value_type,
        "token_form": token_form,
        "observed_token": safe_setting,
        "allowlist_match": allowlist_match,
        "operationally_resolved": operationally_resolved,
        "enum_authority": "official_coinbase_advanced_trade_api_docs",
        "classification": classification,
        "unexpected_field_count": len(
            set(setting_evidence) - _SDK_MARGIN_SETTING_FIELDS
        ),
        "sanitized": True,
        "raw_response_included": False,
    }
    return {
        "margin_setting_evidence": diagnostic,
        "margin_setting_evidence_sha256": canonical_sha256(diagnostic),
    }


def _margin_windows_terminal_context(
    margin_collateral: Any,
) -> dict[str, Any]:
    """Return an exact, identifier-withholding margin-window diagnostic."""

    diagnostic = _classify_margin_windows(margin_collateral)
    return {
        "margin_windows_evidence": diagnostic,
        "margin_windows_evidence_sha256": canonical_sha256(diagnostic),
    }


def _classify_margin_windows(margin_collateral: Any) -> dict[str, Any]:
    """Classify the exact current-window validation boundary without raw values."""

    snapshot = (
        dict(margin_collateral)
        if isinstance(margin_collateral, Mapping)
        else {}
    )
    container_present = "current_margin_windows" in snapshot
    windows = snapshot.get("current_margin_windows")
    container_type = _diagnostic_value_type(
        windows,
        present=container_present,
    )

    def result(
        *,
        row_count_bucket: str,
        classification: str,
        failing_row_index: int | None,
        recognized_profile: str | None,
        failing_field: str | None,
        failing_value_type: str | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "source": "backend_rest_client.get_current_margin_window",
            "stage": "margin_collateral_validation",
            "field_path": "current_margin_windows",
            "container_present": container_present,
            "container_type": container_type,
            "row_count_bucket": row_count_bucket,
            "expected_row_count": 2,
            "failing_row_index": failing_row_index,
            "recognized_profile": recognized_profile,
            "failing_field": failing_field,
            "failing_value_type": failing_value_type,
            "classification": classification,
            "sanitized": True,
            "raw_response_included": False,
            "external_exception_text_included": False,
            "unknown_identifier_values_included": False,
        }

    if not container_present:
        return result(
            row_count_bucket="not_applicable",
            classification="missing_container",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type="missing",
        )
    if not isinstance(windows, list):
        return result(
            row_count_bucket="not_applicable",
            classification="non_list_container",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type=container_type,
        )
    row_count_bucket = {
        0: "zero",
        1: "one",
        2: "expected_two",
    }.get(len(windows), "more_than_two")
    if len(windows) != 2:
        return result(
            row_count_bucket=row_count_bucket,
            classification="unexpected_row_count",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="current_margin_windows",
            failing_value_type="sequence",
        )

    observed_profiles: set[str] = set()
    for index, item in enumerate(windows):
        if not isinstance(item, Mapping):
            return result(
                row_count_bucket=row_count_bucket,
                classification="non_mapping_row",
                failing_row_index=index,
                recognized_profile=None,
                failing_field="row",
                failing_value_type=_diagnostic_value_type(item, present=True),
            )
        window = dict(item)
        profile_present = "profile" in window
        profile = window.get("profile")
        profile_type = _diagnostic_value_type(
            profile,
            present=profile_present,
        )
        if not profile_present:
            profile_classification = "profile_missing"
        elif profile is None:
            profile_classification = "profile_null"
        elif not isinstance(profile, str):
            profile_classification = "profile_non_string"
        elif (
            profile != profile.strip()
            or _SAFE_MARGIN_WINDOW_TOKEN.fullmatch(profile) is None
        ):
            profile_classification = "profile_malformed_string"
        elif profile not in FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES:
            profile_classification = "profile_unrecognized_enum_token"
        else:
            profile_classification = "ready"
        if profile_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=profile_classification,
                failing_row_index=index,
                recognized_profile=None,
                failing_field="profile",
                failing_value_type=profile_type,
            )
        recognized_profile = FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES[profile]
        if profile in observed_profiles:
            return result(
                row_count_bucket=row_count_bucket,
                classification="duplicate_profile",
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="profile",
                failing_value_type="string",
            )
        observed_profiles.add(profile)

        status_present = "status" in window
        status = window.get("status")
        status_type = _diagnostic_value_type(status, present=status_present)
        if not status_present:
            status_classification = "status_missing"
        elif status is None:
            status_classification = "status_null"
        elif not isinstance(status, str):
            status_classification = "status_non_string"
        elif status != "ready":
            status_classification = "status_not_ready"
        else:
            status_classification = "ready"
        if status_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=status_classification,
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="status",
                failing_value_type=status_type,
            )

        margin_window_present = "margin_window" in window
        margin_window = window.get("margin_window")
        margin_window_type = _diagnostic_value_type(
            margin_window,
            present=margin_window_present,
        )
        if not margin_window_present:
            container_classification = "margin_window_missing"
        elif margin_window is None:
            container_classification = "margin_window_null"
        elif not isinstance(margin_window, Mapping):
            container_classification = "margin_window_non_mapping"
        else:
            container_classification = "ready"
        if container_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=container_classification,
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="margin_window",
                failing_value_type=margin_window_type,
            )

        margin_window_mapping = dict(margin_window)
        window_type_present = "margin_window_type" in margin_window_mapping
        window_type = margin_window_mapping.get("margin_window_type")
        window_type_value_type = _diagnostic_value_type(
            window_type,
            present=window_type_present,
        )
        if not window_type_present:
            window_type_classification = "margin_window_type_missing"
        elif window_type is None:
            window_type_classification = "margin_window_type_null"
        elif not isinstance(window_type, str):
            window_type_classification = "margin_window_type_non_string"
        elif (
            window_type != window_type.strip()
            or _SAFE_MARGIN_WINDOW_TOKEN.fullmatch(window_type) is None
        ):
            window_type_classification = (
                "margin_window_type_malformed_string"
            )
        elif (
            window_type
            not in FUTURES_PREVIEW_OPERATIONAL_CURRENT_MARGIN_WINDOW_TYPES
        ):
            window_type_classification = (
                "margin_window_type_not_exact_operational_enum_token"
            )
        else:
            window_type_classification = "ready"
        if window_type_classification != "ready":
            return result(
                row_count_bucket=row_count_bucket,
                classification=window_type_classification,
                failing_row_index=index,
                recognized_profile=recognized_profile,
                failing_field="margin_window_type",
                failing_value_type=window_type_value_type,
            )

    if observed_profiles != set(FUTURES_PREVIEW_EXPECTED_MARGIN_PROFILES):
        return result(
            row_count_bucket=row_count_bucket,
            classification="expected_profile_set_incomplete",
            failing_row_index=None,
            recognized_profile=None,
            failing_field="expected_profile_set",
            failing_value_type=None,
        )
    return result(
        row_count_bucket=row_count_bucket,
        classification="ready",
        failing_row_index=None,
        recognized_profile=None,
        failing_field=None,
        failing_value_type=None,
    )


def _diagnostic_value_type(value: Any, *, present: bool) -> str:
    if not present:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return "sequence"
    return "other"


def _preview_request(candidate: Mapping[str, str]) -> dict[str, Any]:
    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": candidate["limit_price"],
                "post_only": True,
            }
        },
    }


def _seal_ready_plan(
    *,
    claim: Mapping[str, Any],
    binding: Mapping[str, Any],
    candidate: Mapping[str, Any],
    preview_request: Mapping[str, Any],
    preview_response: Mapping[str, Any],
    permissions: Any,
    portfolios: Any,
    product: Any,
    book: Any,
    positions: Any,
    margin_collateral: Any,
) -> dict[str, Any]:
    """Build the canonical fixed plan object suitable for later sealing."""

    sanitized_margin = _sanitized_margin_collateral_evidence(margin_collateral)
    liquidation_source = str(preview_response["liquidation_evidence_source"])
    if liquidation_source == "current_and_projected_liquidation_buffer":
        liquidation_evidence = {
            "current_liquidation_buffer": preview_response[
                "current_liquidation_buffer"
            ],
            "projected_liquidation_buffer": preview_response[
                "projected_liquidation_buffer"
            ],
        }
    else:
        liquidation_evidence = {
            "margin_ratio_data": _mapping(preview_response["margin_ratio_data"]),
            "predicted_liquidation_price": preview_response[
                "predicted_liquidation_price"
            ],
        }
    return {
        "schema_version": _SCHEMA_VERSION,
        "slice_id": claim["artifact_type"],
        "actor_id": claim["actor_id"],
        "roles": list(claim["roles"]),
        "correlation_id": claim["correlation_id"],
        "idempotency_key": claim["idempotency_key"],
        "predecessor_binding": dict(claim["predecessor_binding"]),
        "profile_binding": {
            "profile_label": "Default",
            "portfolio_type": "DEFAULT",
            "portfolio_id": binding.get("observed_portfolio_id"),
            "selection_authority": "cdp_api_key_permissioned_portfolio",
            "request_portfolio_override_allowed": False,
        },
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "contract_count": "1",
        "candidate": dict(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
        "authoritative_preview": {
            "preview_id": preview_response["preview_id"],
            "preview_response": dict(preview_response),
            "preview_response_sha256": canonical_sha256(preview_response),
            "candidate_binding": dict(preview_response["candidate_binding"]),
            "commission_total": preview_response["commission_total"],
            "order_margin_total": preview_response["order_margin_total"],
            "liquidation_evidence_source": liquidation_source,
            "liquidation_evidence": liquidation_evidence,
            "margin_collateral_evidence_sha256": canonical_sha256(
                sanitized_margin
            ),
        },
        "caps": dict(claim["caps"]),
        "attempt_policy": {
            "preview_order": 1,
            "retry": 0,
            "fallback": 0,
            "create_order": 0,
            "cancel_order": 0,
            "close_position": 0,
            "reduce_position": 0,
        },
        "preflight_evidence_hashes": {
            "permissions": canonical_sha256(permissions),
            "portfolio_catalog": canonical_sha256(portfolios),
            "product": canonical_sha256(product),
            "market": canonical_sha256(book),
            "positions": canonical_sha256(positions),
            "margin_collateral": canonical_sha256(margin_collateral),
        },
        "no_live_posture": {
            "order_creation_authorized": False,
            "order_cancellation_authorized": False,
            "position_close_authorized": False,
            "position_reduce_authorized": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "execution_marker_created": False,
            "attempt_ledger_created": False,
            "runtime_created": False,
        },
        "canonicalization": "sorted_keys_compact_utf8_json",
        "hash_algorithm": "sha256",
    }


def _zero_attempt_counters() -> dict[str, int]:
    return {
        "preview_order": 0,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }


def _zero_read_counters() -> dict[str, int]:
    return {
        "api_key_permissions": 0,
        "portfolio_catalog": 0,
        "product": 0,
        "best_bid_ask": 0,
        "futures_positions": 0,
        "futures_margin_collateral": 0,
    }


def _record_sha256(record: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview artifact write was incomplete"
            )
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview artifact directory sync failed"
        ) from exc
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _mapping(value: Any) -> dict[str, Any]:
    normalized = _plain(value)
    return dict(normalized) if isinstance(normalized, Mapping) else {}


def _decimal(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"futures_preview_{name}_invalid") from exc


def _positive_decimal(value: Any, name: str) -> Decimal:
    result = _decimal(value, name)
    if not result.is_finite() or result <= 0:
        raise ValueError(f"futures_preview_{name}_invalid")
    return result


def _usd_money_value(value: Any, name: str) -> Decimal:
    money = _mapping(value)
    if money.get("currency") != "USD":
        raise ValueError(f"futures_preview_{name}_currency_invalid")
    result = _decimal(money.get("value"), name)
    if not result.is_finite() or result < 0:
        raise ValueError(f"futures_preview_{name}_invalid")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _notional_text(value: Decimal) -> str:
    text = format(value, "f")
    whole, separator, fraction = text.partition(".")
    if not separator:
        return f"{whole}.00"
    trimmed_fraction = fraction.rstrip("0")
    if not trimmed_fraction:
        return f"{whole}.00"
    return f"{whole}.{trimmed_fraction.ljust(2, '0')}"


def _exact_pricebook(book: Mapping[str, Any]) -> dict[str, Any]:
    rows = book.get("pricebooks")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("futures_preview_pricebook_missing")
    matches = [
        _mapping(row)
        for row in rows
        if _mapping(row).get("product_id") == FUTURES_PREVIEW_PRODUCT_ID
    ]
    if len(matches) != 1:
        raise ValueError("futures_preview_pricebook_ambiguous")
    return matches[0]


def _top_price(pricebook: Mapping[str, Any], side: str) -> Decimal:
    levels = pricebook.get(side)
    if not isinstance(levels, Sequence) or not levels:
        raise ValueError(f"futures_preview_{side}_missing")
    return _positive_decimal(_mapping(levels[0]).get("price"), f"{side}_price")


def _validate_market_freshness(
    pricebook: Mapping[str, Any],
    observed_at: datetime,
) -> None:
    raw = str(pricebook.get("time") or "").strip()
    if not raw:
        raise ValueError("futures_preview_market_time_missing")
    try:
        market_time = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("futures_preview_market_time_invalid") from exc
    if market_time.tzinfo is None:
        raise ValueError("futures_preview_market_time_unzoned")
    age_seconds = (observed_at.astimezone(timezone.utc) - market_time.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -5 or age_seconds > 30:
        raise ValueError("futures_preview_market_stale")


def _position_contracts(positions: Any, product_id: str) -> Decimal:
    normalized = _plain(positions)
    if isinstance(normalized, Mapping):
        candidate = normalized.get(product_id)
        rows = [candidate] if candidate is not None else []
    elif isinstance(normalized, Sequence) and not isinstance(
        normalized, (str, bytes, bytearray)
    ):
        rows = [
            row
            for row in normalized
            if _mapping(row).get("product_id") == product_id
        ]
    else:
        raise ValueError("futures_preview_positions_ambiguous")
    if len(rows) > 1:
        raise ValueError("futures_preview_positions_ambiguous")
    if not rows:
        return Decimal("0")
    row = _mapping(rows[0])
    return abs(
        _decimal(
            row.get("number_of_contracts", row.get("net_size", "0")),
            "position_contracts",
        )
    )


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray))
    ):
        return bool(value)
    return True


def _timestamp(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
