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
FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "futures_exact_no_live_preview_slice_2.jsonl"
)
DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "futures_exact_no_live_preview_slice_2r1.jsonl"
)
FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256 = (
    "9b15da86c172eca46d4b3dc0fc2b81e9b325df9a1e2f75fef79362f538e2d5ff"
)
FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256 = (
    "3b09cb9dfe02991dc886a1c6f041330d417ff11a0f1d45e3734bdc59bfb219b8"
)
FUTURES_PREVIEW_PREDECESSOR_DEVICE = 66305
FUTURES_PREVIEW_PREDECESSOR_INODE = 42312964
FUTURES_PREVIEW_PREDECESSOR_SIZE = 3043
FUTURES_PREVIEW_PREDECESSOR_MODE = 0o400
FUTURES_PREVIEW_PREDECESSOR_MTIME_NS = 1783968539951853688
_SCHEMA_VERSION = "1"
_ARTIFACT_TYPE = "futures_exact_no_live_preview_slice_2r1"
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class FuturesOrderPreviewArtifactError(RuntimeError):
    """Raised when one-shot Preview evidence is unavailable or unsafe."""


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
) -> dict[str, Any]:
    """Read and bind the immutable terminal Slice 2 predecessor."""

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
    if (
        not hmac.compare_digest(evidence_sha256, expected_evidence_sha256)
        or evidence.get("artifact_type")
        != "futures_exact_no_live_preview_slice_2"
        or evidence.get("status") != "blocked"
        or evidence.get("outcome") != "blocked"
        or evidence.get("blocker")
        != (
            "preflight_or_preview_blocked:ValueError:"
            "futures_preview_product_status_blocked"
        )
        or attempts != expected_zero_attempts
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

    return {
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


def validate_production_futures_order_preview_predecessor() -> dict[str, Any]:
    """Validate the exact operator-authorized Slice 2 predecessor."""

    return validate_futures_order_preview_predecessor(
        FUTURES_PREVIEW_PREDECESSOR_ARTIFACT_PATH,
        expected_file_sha256=FUTURES_PREVIEW_PREDECESSOR_FILE_SHA256,
        expected_evidence_sha256=FUTURES_PREVIEW_PREDECESSOR_EVIDENCE_SHA256,
        expected_device=FUTURES_PREVIEW_PREDECESSOR_DEVICE,
        expected_inode=FUTURES_PREVIEW_PREDECESSOR_INODE,
        expected_size=FUTURES_PREVIEW_PREDECESSOR_SIZE,
        expected_mode=FUTURES_PREVIEW_PREDECESSOR_MODE,
        expected_mtime_ns=FUTURES_PREVIEW_PREDECESSOR_MTIME_NS,
    )


class FuturesOrderPreviewProducer:
    """Consume one fixed authorization to produce Preview-only evidence."""

    def __init__(
        self,
        *,
        rest_client: Any,
        store: FuturesOrderPreviewArtifactStore,
        predecessor_binding: Mapping[str, Any],
        predecessor_validator: Callable[[], Mapping[str, Any]],
        now: Callable[[], datetime] | None = None,
        correlation_id_factory: Callable[[], str] | None = None,
        idempotency_key_factory: Callable[[], str] | None = None,
    ) -> None:
        self.rest_client = rest_client
        self.store = store
        self.predecessor_binding = dict(predecessor_binding)
        self.predecessor_validator = predecessor_validator
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.correlation_id_factory = correlation_id_factory or (lambda: str(uuid4()))
        self.idempotency_key_factory = idempotency_key_factory or (lambda: str(uuid4()))

    def build_claim(self) -> dict[str, Any]:
        """Build the fixed claim without calling Coinbase."""

        return {
            "artifact_type": _ARTIFACT_TYPE,
            "claim_status": "reserved",
            "predecessor_binding": dict(self.predecessor_binding),
            "reserved_at": _timestamp(self.now()),
            "actor_id": FUTURES_PREVIEW_ACTOR_ID,
            "roles": [FUTURES_PREVIEW_ROLE],
            "correlation_id": self.correlation_id_factory(),
            "idempotency_key": self.idempotency_key_factory(),
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
            margin_collateral = _plain(
                self.rest_client.get_futures_margin_collateral_snapshot()
            )
            available_margin = validate_margin_collateral_evidence(
                margin_collateral
            )
            observed_at = self.now()
            candidate = build_futures_order_preview_candidate(
                product=product,
                book=book,
                positions=positions,
                observed_at=observed_at,
            )
            preview_request = _preview_request(candidate)
            terminal_context = _terminal_attempt_context(
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
            terminal_context["preview_response"] = preview_response
            terminal_context["preview_response_sha256"] = canonical_sha256(
                preview_response
            )
            normalized_preview = validate_preview_response(preview_response)
            normalized_preview = validate_preview_against_candidate(
                normalized_preview,
                candidate,
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
            blocker = f"preflight_or_preview_blocked:{type(exc).__name__}:{exc}"
            if transition_blocker is not None and transition_blocker not in blocker:
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
    """Require authoritative fee, margin, and liquidation Preview evidence."""

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
    if legacy_liquidation_ready:
        for field in (
            "current_liquidation_buffer",
            "projected_liquidation_buffer",
        ):
            value = _decimal(response[field], field)
            if not value.is_finite() or value < 0:
                raise ValueError(
                    f"futures_preview_liquidation_{field}_not_finite_or_negative"
                )
        response["liquidation_evidence_source"] = (
            "current_and_projected_liquidation_buffer"
        )
    elif replacement_liquidation_ready:
        margin_ratio_data = _mapping(response["margin_ratio_data"])
        for field in ("current_margin_ratio", "projected_margin_ratio"):
            value = _decimal(margin_ratio_data.get(field), field)
            if not value.is_finite() or value < 0:
                raise ValueError(
                    f"futures_preview_margin_ratio_{field}_not_finite_or_negative"
                )
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
        response["liquidation_evidence_source"] = (
            "margin_ratio_data_and_predicted_liquidation_price"
        )
    else:
        raise ValueError("futures_preview_response_liquidation_evidence_incomplete")
    return response


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
    if not str(measure.get("margin_window_type") or "").strip():
        raise ValueError("futures_preview_margin_window_measure_ambiguous")
    for field in ("maintenance_margin", "liquidation_buffer"):
        amount = _decimal(measure.get(field), field)
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"futures_preview_margin_{field}_invalid")

    setting = _mapping(evidence.get("intraday_margin_setting")).get("setting")
    if setting not in {
        "INTRADAY_MARGIN_SETTING_ENABLED",
        "INTRADAY_MARGIN_SETTING_DISABLED",
    }:
        raise ValueError("futures_preview_margin_setting_ambiguous")
    windows = evidence.get("current_margin_windows")
    if not isinstance(windows, list) or len(windows) != 2:
        raise ValueError("futures_preview_margin_windows_ambiguous")
    expected_profiles = {
        "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
        "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
    }
    observed_profiles: set[str] = set()
    for item in windows:
        window = _mapping(item)
        profile = str(window.get("profile") or "")
        window_evidence = _mapping(window.get("margin_window"))
        if (
            profile not in expected_profiles
            or profile in observed_profiles
            or window.get("status") != "ready"
            or not str(
                window_evidence.get("margin_window_type") or ""
            ).strip()
        ):
            raise ValueError("futures_preview_margin_windows_ambiguous")
        observed_profiles.add(profile)
    if observed_profiles != expected_profiles:
        raise ValueError("futures_preview_margin_windows_ambiguous")
    if not isinstance(evidence.get("futures_sweeps"), list):
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
    evidence: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "type": "admin_futures_order_preview",
        "artifact_type": _ARTIFACT_TYPE,
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
        "permission_evidence": _plain(permissions),
        "permission_evidence_sha256": canonical_sha256(permissions),
        "portfolio_catalog_evidence": _plain(portfolios),
        "portfolio_catalog_sha256": canonical_sha256(portfolios),
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "product_evidence": _plain(product),
        "product_evidence_sha256": canonical_sha256(product),
        "market_evidence": _plain(book),
        "market_evidence_sha256": canonical_sha256(book),
        "position_evidence": _plain(positions),
        "position_evidence_sha256": canonical_sha256(positions),
        "margin_collateral_evidence": _plain(margin_collateral),
        "margin_collateral_evidence_sha256": canonical_sha256(margin_collateral),
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
        "artifact_type": _ARTIFACT_TYPE,
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
        evidence.update(_plain(context))
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

    return {
        "portfolio_id": binding.get("observed_portfolio_id"),
        "portfolio_binding": dict(binding),
        "permission_evidence": _plain(permissions),
        "permission_evidence_sha256": canonical_sha256(permissions),
        "portfolio_catalog_evidence": _plain(portfolios),
        "portfolio_catalog_sha256": canonical_sha256(portfolios),
        "product_evidence": _plain(product),
        "product_evidence_sha256": canonical_sha256(product),
        "market_evidence": _plain(book),
        "market_evidence_sha256": canonical_sha256(book),
        "position_evidence": _plain(positions),
        "position_evidence_sha256": canonical_sha256(positions),
        "margin_collateral_evidence": _plain(margin_collateral),
        "margin_collateral_evidence_sha256": canonical_sha256(margin_collateral),
        "candidate": dict(candidate),
        "candidate_sha256": canonical_sha256(candidate),
        "preview_request": dict(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
    }


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
        "slice_id": _ARTIFACT_TYPE,
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
                margin_collateral
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
