"""Durable at-most-once journal for the finite Slice 3 read budget.

This module owns no Coinbase client and performs no exchange access.  It wraps
an injected zero-argument read delegate with a process-safe, fsynced boundary:
once a plan/slot pair is reserved, it is consumed even if the process exits
before a terminal record can be written.  Only fixed declaration metadata and
SHA-256 evidence digests are persisted; delegate values and exceptions are
never serialized.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import RLock
from typing import Any, TypeVar

from application.admin_api.futures_terminal_roundtrip import Slice3ReadSlot


SLICE3_READ_JOURNAL_PATH_ENV = "COINBASE_SLICE3_READ_JOURNAL_PATH"
DEFAULT_SLICE3_READ_JOURNAL_PATH = Path(
    "runtime_state/futures_slice3_read_journal.jsonl"
)
SLICE3_MAX_READ_JOURNAL_BYTES = 1_048_576
SLICE3_READ_RECORD_SCHEMA_VERSION = "slice3-read-journal-record-v1"
SLICE3_READ_GENESIS_SHA256 = "0" * 64

SLICE3_MARGIN_FACADE_SOURCE_VECTOR = (
    ("get_futures_balance_summary", 1),
    ("get_intraday_margin_setting", 1),
    ("get_current_margin_window", 2),
    ("list_futures_sweeps", 1),
)

_OPEN_ORDER_SOURCE_VECTOR = (
    ("list_orders_active_transitional", 1),
)
_POSITION_SOURCE_VECTOR = (("list_futures_positions", 1),)
_ORDER_SOURCE_VECTOR = (("list_orders", 1),)
_MARKET_SOURCE_VECTOR = (("get_best_bid_ask", 1),)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class Slice3ReadJournalError(RuntimeError):
    """Raised when durable read state is invalid or unsafe."""


class Slice3ReadConsumedError(Slice3ReadJournalError):
    """Raised when a read boundary has already been reserved."""


class Slice3ReadDelegateError(Slice3ReadJournalError):
    """Sanitized terminal error raised after a delegate boundary."""


class Slice3ReadRecordEvent(str, Enum):
    """The two append-only events permitted for one read slot."""

    BOUNDARY_RESERVED = "boundary_reserved"
    CONSUMED = "consumed"


class Slice3ReadOutcome(str, Enum):
    """Sanitized state of a reserved read slot."""

    RESERVED = "reserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class Slice3ReadDeclaration:
    """Fixed physical-read declaration for one logical read slot."""

    slot: Slice3ReadSlot
    evidence_kind: str
    slot_attempt_count: int
    subread_count: int
    source_vector: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "slot": self.slot.value,
            "evidence_kind": self.evidence_kind,
            "slot_attempt_count": self.slot_attempt_count,
            "subread_count": self.subread_count,
            "source_vector": [
                {"source": source, "attempt_count": count}
                for source, count in self.source_vector
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> Slice3ReadDeclaration:
        if not isinstance(value, dict) or set(value) != {
            "slot",
            "evidence_kind",
            "slot_attempt_count",
            "subread_count",
            "source_vector",
        }:
            raise Slice3ReadJournalError("slice3_read_declaration_invalid")
        source_rows = value.get("source_vector")
        if not isinstance(source_rows, list):
            raise Slice3ReadJournalError("slice3_read_declaration_invalid")
        source_vector: list[tuple[str, int]] = []
        for row in source_rows:
            if not isinstance(row, dict) or set(row) != {
                "source",
                "attempt_count",
            }:
                raise Slice3ReadJournalError("slice3_read_declaration_invalid")
            source = row.get("source")
            count = row.get("attempt_count")
            if (
                not isinstance(source, str)
                or _SOURCE_NAME_PATTERN.fullmatch(source) is None
                or type(count) is not int
                or count <= 0
            ):
                raise Slice3ReadJournalError("slice3_read_declaration_invalid")
            source_vector.append((source, count))
        try:
            slot = Slice3ReadSlot(value.get("slot"))
        except (TypeError, ValueError):
            raise Slice3ReadJournalError("slice3_read_declaration_invalid") from None
        evidence_kind = value.get("evidence_kind")
        slot_attempt_count = value.get("slot_attempt_count")
        subread_count = value.get("subread_count")
        if (
            not isinstance(evidence_kind, str)
            or _SOURCE_NAME_PATTERN.fullmatch(evidence_kind) is None
            or type(slot_attempt_count) is not int
            or slot_attempt_count != 1
            or type(subread_count) is not int
            or subread_count <= 0
            or subread_count != sum(count for _, count in source_vector)
        ):
            raise Slice3ReadJournalError("slice3_read_declaration_invalid")
        return cls(
            slot=slot,
            evidence_kind=evidence_kind,
            slot_attempt_count=slot_attempt_count,
            subread_count=subread_count,
            source_vector=tuple(source_vector),
        )


def _declaration(
    slot: Slice3ReadSlot,
    evidence_kind: str,
    source_vector: tuple[tuple[str, int], ...],
) -> Slice3ReadDeclaration:
    return Slice3ReadDeclaration(
        slot=slot,
        evidence_kind=evidence_kind,
        slot_attempt_count=1,
        subread_count=sum(count for _, count in source_vector),
        source_vector=source_vector,
    )


_SLICE3_READ_DECLARATIONS = {
    Slice3ReadSlot.PRE_CREATE_OPEN_ORDERS: _declaration(
        Slice3ReadSlot.PRE_CREATE_OPEN_ORDERS,
        "open_order_zero_proof",
        _OPEN_ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.PRE_CREATE_POSITION: _declaration(
        Slice3ReadSlot.PRE_CREATE_POSITION,
        "position_observation",
        _POSITION_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.PRE_CREATE_MARGIN: _declaration(
        Slice3ReadSlot.PRE_CREATE_MARGIN,
        "margin_summary",
        SLICE3_MARGIN_FACADE_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.POST_CREATE_ORDER: _declaration(
        Slice3ReadSlot.POST_CREATE_ORDER,
        "exact_order_evidence",
        _ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.POST_CREATE_POSITION: _declaration(
        Slice3ReadSlot.POST_CREATE_POSITION,
        "position_observation",
        _POSITION_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.POST_CANCEL_TERMINAL_ORDER: _declaration(
        Slice3ReadSlot.POST_CANCEL_TERMINAL_ORDER,
        "exact_order_evidence",
        _ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.PRE_CLOSE_POSITION: _declaration(
        Slice3ReadSlot.PRE_CLOSE_POSITION,
        "position_observation",
        _POSITION_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.PRE_CLOSE_MARKET: _declaration(
        Slice3ReadSlot.PRE_CLOSE_MARKET,
        "market_reference",
        _MARKET_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.PRE_CLOSE_OPEN_ORDERS: _declaration(
        Slice3ReadSlot.PRE_CLOSE_OPEN_ORDERS,
        "open_order_zero_proof",
        _OPEN_ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.POST_CLOSE_ORDER: _declaration(
        Slice3ReadSlot.POST_CLOSE_ORDER,
        "exact_order_evidence",
        _ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.FINAL_POSITION: _declaration(
        Slice3ReadSlot.FINAL_POSITION,
        "position_observation",
        _POSITION_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.FINAL_OPEN_ORDERS: _declaration(
        Slice3ReadSlot.FINAL_OPEN_ORDERS,
        "open_order_zero_proof",
        _OPEN_ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.FINAL_MARGIN: _declaration(
        Slice3ReadSlot.FINAL_MARGIN,
        "margin_summary",
        SLICE3_MARGIN_FACADE_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID: _declaration(
        Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID,
        "exact_order_evidence",
        _ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_POSITION: _declaration(
        Slice3ReadSlot.RECOVERY_POSITION,
        "position_observation",
        _POSITION_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_POST_CANCEL_TERMINAL_ORDER: _declaration(
        Slice3ReadSlot.RECOVERY_POST_CANCEL_TERMINAL_ORDER,
        "exact_order_evidence",
        _ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_POST_CANCEL_POSITION: _declaration(
        Slice3ReadSlot.RECOVERY_POST_CANCEL_POSITION,
        "position_observation",
        _POSITION_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_MARKET: _declaration(
        Slice3ReadSlot.RECOVERY_MARKET,
        "market_reference",
        _MARKET_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_PRE_CLOSE_OPEN_ORDERS: _declaration(
        Slice3ReadSlot.RECOVERY_PRE_CLOSE_OPEN_ORDERS,
        "open_order_zero_proof",
        _OPEN_ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID: _declaration(
        Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID,
        "exact_order_evidence",
        _ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_FINAL_POSITION: _declaration(
        Slice3ReadSlot.RECOVERY_FINAL_POSITION,
        "position_observation",
        _POSITION_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_FINAL_OPEN_ORDERS: _declaration(
        Slice3ReadSlot.RECOVERY_FINAL_OPEN_ORDERS,
        "open_order_zero_proof",
        _OPEN_ORDER_SOURCE_VECTOR,
    ),
    Slice3ReadSlot.RECOVERY_FINAL_MARGIN: _declaration(
        Slice3ReadSlot.RECOVERY_FINAL_MARGIN,
        "margin_summary",
        SLICE3_MARGIN_FACADE_SOURCE_VECTOR,
    ),
}

if set(_SLICE3_READ_DECLARATIONS) != set(Slice3ReadSlot):
    raise RuntimeError("slice3_read_declaration_set_incomplete")


def slice3_read_declaration(slot: Slice3ReadSlot) -> Slice3ReadDeclaration:
    """Return the immutable declaration for an exact enum slot."""

    if not isinstance(slot, Slice3ReadSlot):
        raise Slice3ReadJournalError("slice3_read_slot_invalid")
    return _SLICE3_READ_DECLARATIONS[slot]


def configured_slice3_read_journal_path() -> Path:
    """Return the fixed runtime path without touching the filesystem."""

    configured = os.environ.get(SLICE3_READ_JOURNAL_PATH_ENV)
    return Path(configured) if configured else DEFAULT_SLICE3_READ_JOURNAL_PATH


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise Slice3ReadJournalError("slice3_read_evidence_invalid") from None


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: object, reason: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise Slice3ReadJournalError(reason)
    return value


def _semantic_key(plan_sha256: str, slot: Slice3ReadSlot) -> str:
    return _canonical_sha256(
        {
            "schema_version": "slice3-read-semantic-key-v1",
            "plan_sha256": plan_sha256,
            "slot": slot.value,
        }
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise Slice3ReadJournalError("slice3_read_record_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise Slice3ReadJournalError("slice3_read_record_invalid") from None
    if parsed.tzinfo is None:
        raise Slice3ReadJournalError("slice3_read_record_invalid")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Slice3ReadRecord:
    """One hash-chained, allowlisted read-journal row."""

    schema_version: str
    event: Slice3ReadRecordEvent
    recorded_at: datetime
    semantic_key: str
    plan_sha256: str
    slot: Slice3ReadSlot
    declaration: Slice3ReadDeclaration
    outcome: Slice3ReadOutcome
    reason_code: str
    evidence_sha256: str | None
    previous_record_sha256: str
    record_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event": self.event.value,
            "recorded_at": self.recorded_at.astimezone(timezone.utc).isoformat(),
            "semantic_key": self.semantic_key,
            "plan_sha256": self.plan_sha256,
            "slot": self.slot.value,
            "declaration": self.declaration.to_dict(),
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "evidence_sha256": self.evidence_sha256,
            "previous_record_sha256": self.previous_record_sha256,
            "record_sha256": self.record_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Slice3ReadRecord:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "event",
            "recorded_at",
            "semantic_key",
            "plan_sha256",
            "slot",
            "declaration",
            "outcome",
            "reason_code",
            "evidence_sha256",
            "previous_record_sha256",
            "record_sha256",
        }:
            raise Slice3ReadJournalError("slice3_read_record_invalid")
        try:
            event = Slice3ReadRecordEvent(value.get("event"))
            slot = Slice3ReadSlot(value.get("slot"))
            outcome = Slice3ReadOutcome(value.get("outcome"))
        except (TypeError, ValueError):
            raise Slice3ReadJournalError("slice3_read_record_invalid") from None
        schema_version = value.get("schema_version")
        reason_code = value.get("reason_code")
        evidence_sha256 = value.get("evidence_sha256")
        if (
            schema_version != SLICE3_READ_RECORD_SCHEMA_VERSION
            or not isinstance(reason_code, str)
            or reason_code
            not in {
                "read_boundary_reserved",
                "read_succeeded",
                "read_delegate_exception",
                "read_evidence_invalid",
                "read_process_interrupted",
            }
            or evidence_sha256 is not None
            and not isinstance(evidence_sha256, str)
        ):
            raise Slice3ReadJournalError("slice3_read_record_invalid")
        semantic_key = _require_sha256(
            value.get("semantic_key"),
            "slice3_read_record_invalid",
        )
        plan_sha256 = _require_sha256(
            value.get("plan_sha256"),
            "slice3_read_record_invalid",
        )
        previous_record_sha256 = _require_sha256(
            value.get("previous_record_sha256"),
            "slice3_read_record_invalid",
        )
        record_sha256 = _require_sha256(
            value.get("record_sha256"),
            "slice3_read_record_invalid",
        )
        if evidence_sha256 is not None:
            _require_sha256(
                evidence_sha256,
                "slice3_read_record_invalid",
            )
        return cls(
            schema_version=schema_version,
            event=event,
            recorded_at=_parse_aware_datetime(value.get("recorded_at")),
            semantic_key=semantic_key,
            plan_sha256=plan_sha256,
            slot=slot,
            declaration=Slice3ReadDeclaration.from_dict(value.get("declaration")),
            outcome=outcome,
            reason_code=reason_code,
            evidence_sha256=evidence_sha256,
            previous_record_sha256=previous_record_sha256,
            record_sha256=record_sha256,
        )


def _record_payload(record: Slice3ReadRecord) -> dict[str, object]:
    payload = record.to_dict()
    del payload["record_sha256"]
    return payload


def _make_record(
    *,
    event: Slice3ReadRecordEvent,
    plan_sha256: str,
    slot: Slice3ReadSlot,
    declaration: Slice3ReadDeclaration,
    outcome: Slice3ReadOutcome,
    reason_code: str,
    evidence_sha256: str | None,
    previous_record_sha256: str,
) -> Slice3ReadRecord:
    record = Slice3ReadRecord(
        schema_version=SLICE3_READ_RECORD_SCHEMA_VERSION,
        event=event,
        recorded_at=_utc_now(),
        semantic_key=_semantic_key(plan_sha256, slot),
        plan_sha256=plan_sha256,
        slot=slot,
        declaration=declaration,
        outcome=outcome,
        reason_code=reason_code,
        evidence_sha256=evidence_sha256,
        previous_record_sha256=previous_record_sha256,
        record_sha256=SLICE3_READ_GENESIS_SHA256,
    )
    return Slice3ReadRecord(
        **{
            **record.__dict__,
            "record_sha256": _canonical_sha256(_record_payload(record)),
        }
    )


_Result = TypeVar("_Result")


class FileSlice3ReadJournal:
    """Owner-only, process-safe journal for logical Slice 3 read slots."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = (
            Path(path) if path is not None else configured_slice3_read_journal_path()
        )
        self._lock = RLock()

    @staticmethod
    def _validate_declaration(
        slot: Slice3ReadSlot,
        declaration: Slice3ReadDeclaration,
    ) -> None:
        if not isinstance(
            declaration, Slice3ReadDeclaration
        ) or declaration != slice3_read_declaration(slot):
            raise Slice3ReadJournalError("slice3_read_declaration_invalid")

    @staticmethod
    def _validate_request(
        plan_sha256: str,
        slot: Slice3ReadSlot,
        declaration: Slice3ReadDeclaration,
    ) -> None:
        _require_sha256(
            plan_sha256,
            "slice3_read_plan_sha256_invalid",
        )
        if not isinstance(slot, Slice3ReadSlot):
            raise Slice3ReadJournalError("slice3_read_slot_invalid")
        FileSlice3ReadJournal._validate_declaration(slot, declaration)

    def _ensure_safe_parent(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            parent = Path(os.path.abspath(self.path.parent))
            chain = [parent, *parent.parents]
            for component in reversed(chain):
                metadata = os.lstat(component)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise Slice3ReadJournalError("slice3_read_journal_unsafe")
        except Slice3ReadJournalError:
            raise
        except OSError:
            raise Slice3ReadJournalError("slice3_read_journal_unsafe") from None

    @staticmethod
    def _metadata_is_safe(metadata: os.stat_result) -> bool:
        return bool(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and stat.S_IMODE(metadata.st_mode) == 0o600
            and metadata.st_nlink == 1
            and metadata.st_size <= SLICE3_MAX_READ_JOURNAL_BYTES
        )

    def _assert_descriptor_safe(self, descriptor: int) -> None:
        try:
            descriptor_metadata = os.fstat(descriptor)
            path_metadata = os.lstat(self.path)
        except OSError:
            raise Slice3ReadJournalError("slice3_read_journal_unsafe") from None
        if (
            not self._metadata_is_safe(descriptor_metadata)
            or not self._metadata_is_safe(path_metadata)
            or stat.S_ISLNK(path_metadata.st_mode)
            or path_metadata.st_dev != descriptor_metadata.st_dev
            or path_metadata.st_ino != descriptor_metadata.st_ino
        ):
            raise Slice3ReadJournalError("slice3_read_journal_unsafe")

    def _open(self) -> int:
        self._ensure_safe_parent()
        try:
            existing_metadata = os.lstat(self.path)
        except FileNotFoundError:
            existing_metadata = None
        except OSError:
            raise Slice3ReadJournalError("slice3_read_journal_unsafe") from None
        if existing_metadata is not None and not self._metadata_is_safe(
            existing_metadata
        ):
            raise Slice3ReadJournalError("slice3_read_journal_unsafe")
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError:
            raise Slice3ReadJournalError("slice3_read_journal_unsafe") from None
        try:
            self._assert_descriptor_safe(descriptor)
        except Slice3ReadJournalError:
            os.close(descriptor)
            raise
        except OSError:
            os.close(descriptor)
            raise Slice3ReadJournalError("slice3_read_journal_unsafe") from None
        return descriptor

    @staticmethod
    def _parse(raw: bytes) -> list[Slice3ReadRecord]:
        if raw and not raw.endswith(b"\n"):
            raise Slice3ReadJournalError("slice3_read_journal_truncated")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            raise Slice3ReadJournalError("slice3_read_journal_not_utf8") from None
        records: list[Slice3ReadRecord] = []
        for line in lines:
            if not line:
                raise Slice3ReadJournalError("slice3_read_journal_blank_row")
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                raise Slice3ReadJournalError("slice3_read_journal_malformed") from None
            records.append(Slice3ReadRecord.from_dict(value))
        FileSlice3ReadJournal._validate_records(records)
        return records

    @staticmethod
    def _validate_records(records: list[Slice3ReadRecord]) -> None:
        previous_sha256 = SLICE3_READ_GENESIS_SHA256
        latest_by_semantic_key: dict[str, Slice3ReadRecord] = {}
        for record in records:
            if (
                record.record_sha256 != _canonical_sha256(_record_payload(record))
                or record.previous_record_sha256 != previous_sha256
            ):
                raise Slice3ReadJournalError("slice3_read_hash_chain_invalid")
            previous_sha256 = record.record_sha256
            if record.semantic_key != _semantic_key(
                record.plan_sha256, record.slot
            ) or record.declaration != slice3_read_declaration(record.slot):
                raise Slice3ReadJournalError("slice3_read_record_binding_invalid")
            previous = latest_by_semantic_key.get(record.semantic_key)
            if record.event is Slice3ReadRecordEvent.BOUNDARY_RESERVED:
                valid = bool(
                    previous is None
                    and record.outcome is Slice3ReadOutcome.RESERVED
                    and record.reason_code == "read_boundary_reserved"
                    and record.evidence_sha256 is None
                )
            else:
                successful = bool(
                    record.outcome is Slice3ReadOutcome.SUCCEEDED
                    and record.reason_code == "read_succeeded"
                    and record.evidence_sha256 is not None
                )
                failed = bool(
                    record.outcome is Slice3ReadOutcome.FAILED
                    and record.reason_code
                    in {
                        "read_delegate_exception",
                        "read_evidence_invalid",
                        "read_process_interrupted",
                    }
                    and record.evidence_sha256 is None
                )
                valid = bool(
                    previous is not None
                    and previous.event is Slice3ReadRecordEvent.BOUNDARY_RESERVED
                    and previous.plan_sha256 == record.plan_sha256
                    and previous.slot is record.slot
                    and previous.declaration == record.declaration
                    and (successful or failed)
                )
            if not valid:
                raise Slice3ReadJournalError("slice3_read_sequence_invalid")
            latest_by_semantic_key[record.semantic_key] = record

    @staticmethod
    def _read_locked(descriptor: int) -> list[Slice3ReadRecord]:
        before = os.fstat(descriptor)
        if before.st_size > SLICE3_MAX_READ_JOURNAL_BYTES:
            raise Slice3ReadJournalError("slice3_read_journal_too_large")
        os.lseek(descriptor, 0, os.SEEK_SET)
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 131_072))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or after.st_size != before.st_size
            or after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
        ):
            raise Slice3ReadJournalError("slice3_read_journal_size_changed")
        return FileSlice3ReadJournal._parse(raw)

    def _append_locked(
        self,
        descriptor: int,
        record: Slice3ReadRecord,
    ) -> None:
        self._assert_descriptor_safe(descriptor)
        encoded = (
            json.dumps(
                record.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        metadata = os.fstat(descriptor)
        if metadata.st_size + len(encoded) > SLICE3_MAX_READ_JOURNAL_BYTES:
            raise Slice3ReadJournalError("slice3_read_journal_too_large")
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise Slice3ReadJournalError("slice3_read_journal_short_write")
            offset += written
        os.fsync(descriptor)
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory = os.open(self.path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self._assert_descriptor_safe(descriptor)

    def _with_exclusive(
        self,
        operation: Callable[[int, list[Slice3ReadRecord]], Slice3ReadRecord],
    ) -> Slice3ReadRecord:
        with self._lock:
            descriptor = self._open()
            locked = False
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                locked = True
                self._assert_descriptor_safe(descriptor)
                return operation(
                    descriptor,
                    self._read_locked(descriptor),
                )
            finally:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    @staticmethod
    def _latest_matching(
        records: list[Slice3ReadRecord],
        semantic_key: str,
    ) -> Slice3ReadRecord | None:
        matching = [record for record in records if record.semantic_key == semantic_key]
        return matching[-1] if matching else None

    def reserve(
        self,
        *,
        plan_sha256: str,
        slot: Slice3ReadSlot,
        declaration: Slice3ReadDeclaration,
    ) -> Slice3ReadRecord:
        """Fsync a read boundary before any delegate can be accessed."""

        self._validate_request(plan_sha256, slot, declaration)
        semantic_key = _semantic_key(plan_sha256, slot)

        def operation(
            descriptor: int,
            records: list[Slice3ReadRecord],
        ) -> Slice3ReadRecord:
            if self._latest_matching(records, semantic_key) is not None:
                raise Slice3ReadConsumedError("slice3_read_slot_consumed")
            previous_sha256 = (
                records[-1].record_sha256 if records else SLICE3_READ_GENESIS_SHA256
            )
            record = _make_record(
                event=Slice3ReadRecordEvent.BOUNDARY_RESERVED,
                plan_sha256=plan_sha256,
                slot=slot,
                declaration=declaration,
                outcome=Slice3ReadOutcome.RESERVED,
                reason_code="read_boundary_reserved",
                evidence_sha256=None,
                previous_record_sha256=previous_sha256,
            )
            self._append_locked(descriptor, record)
            return record

        return self._with_exclusive(operation)

    def _consume(
        self,
        reservation: Slice3ReadRecord,
        *,
        outcome: Slice3ReadOutcome,
        reason_code: str,
        evidence_sha256: str | None,
    ) -> Slice3ReadRecord:
        if (
            not isinstance(reservation, Slice3ReadRecord)
            or reservation.event is not Slice3ReadRecordEvent.BOUNDARY_RESERVED
            or reservation.outcome is not Slice3ReadOutcome.RESERVED
        ):
            raise Slice3ReadJournalError("slice3_read_reservation_invalid")
        if evidence_sha256 is not None:
            _require_sha256(
                evidence_sha256,
                "slice3_read_evidence_sha256_invalid",
            )

        def operation(
            descriptor: int,
            records: list[Slice3ReadRecord],
        ) -> Slice3ReadRecord:
            latest = self._latest_matching(
                records,
                reservation.semantic_key,
            )
            if (
                latest is None
                or latest.record_sha256 != reservation.record_sha256
                or latest.event is not Slice3ReadRecordEvent.BOUNDARY_RESERVED
                or latest != reservation
            ):
                raise Slice3ReadConsumedError("slice3_read_slot_consumed")
            previous_sha256 = (
                records[-1].record_sha256 if records else SLICE3_READ_GENESIS_SHA256
            )
            record = _make_record(
                event=Slice3ReadRecordEvent.CONSUMED,
                plan_sha256=reservation.plan_sha256,
                slot=reservation.slot,
                declaration=reservation.declaration,
                outcome=outcome,
                reason_code=reason_code,
                evidence_sha256=evidence_sha256,
                previous_record_sha256=previous_sha256,
            )
            self._append_locked(descriptor, record)
            return record

        return self._with_exclusive(operation)

    def consume_success(
        self,
        reservation: Slice3ReadRecord,
        *,
        evidence_sha256: str,
    ) -> Slice3ReadRecord:
        """Append a successful terminal digest for a reservation."""

        return self._consume(
            reservation,
            outcome=Slice3ReadOutcome.SUCCEEDED,
            reason_code="read_succeeded",
            evidence_sha256=evidence_sha256,
        )

    def _consume_failure(
        self,
        reservation: Slice3ReadRecord,
        *,
        reason_code: str,
    ) -> Slice3ReadRecord:
        return self._consume(
            reservation,
            outcome=Slice3ReadOutcome.FAILED,
            reason_code=reason_code,
            evidence_sha256=None,
        )

    def recover_reserved_as_failed(
        self,
        *,
        plan_sha256: str,
        slot: Slice3ReadSlot,
        declaration: Slice3ReadDeclaration,
    ) -> Slice3ReadRecord:
        """Terminalize a crash-left reservation without invoking a delegate."""

        self._validate_request(plan_sha256, slot, declaration)
        semantic_key = _semantic_key(plan_sha256, slot)

        def operation(
            descriptor: int,
            records: list[Slice3ReadRecord],
        ) -> Slice3ReadRecord:
            latest = self._latest_matching(records, semantic_key)
            if latest is None:
                raise Slice3ReadJournalError("slice3_read_reservation_missing")
            if latest.event is Slice3ReadRecordEvent.CONSUMED:
                if (
                    latest.outcome is Slice3ReadOutcome.FAILED
                    and latest.reason_code == "read_process_interrupted"
                ):
                    return latest
                raise Slice3ReadConsumedError("slice3_read_slot_consumed")
            if not (
                latest.event is Slice3ReadRecordEvent.BOUNDARY_RESERVED
                and latest.outcome is Slice3ReadOutcome.RESERVED
                and latest.declaration == declaration
                and latest.plan_sha256 == plan_sha256
            ):
                raise Slice3ReadJournalError("slice3_read_reservation_invalid")
            previous_sha256 = records[-1].record_sha256
            recovered = _make_record(
                event=Slice3ReadRecordEvent.CONSUMED,
                plan_sha256=plan_sha256,
                slot=slot,
                declaration=declaration,
                outcome=Slice3ReadOutcome.FAILED,
                reason_code="read_process_interrupted",
                evidence_sha256=None,
                previous_record_sha256=previous_sha256,
            )
            self._append_locked(descriptor, recovered)
            return recovered

        return self._with_exclusive(operation)

    @staticmethod
    def _evidence_sha256(result: object) -> str:
        try:
            sanitizer = getattr(result, "sanitized_evidence", None)
            if not callable(sanitizer):
                raise TypeError
            evidence = sanitizer()
            if not isinstance(evidence, Mapping):
                raise TypeError
            if (
                evidence.get("raw_response_included") is True
                or evidence.get("identifier_values_included") is True
            ):
                raise ValueError
            return _canonical_sha256(evidence)
        except Exception:
            raise Slice3ReadJournalError("slice3_read_evidence_invalid") from None

    def execute(
        self,
        *,
        plan_sha256: str,
        slot: Slice3ReadSlot,
        declaration: Slice3ReadDeclaration,
        delegate: Callable[[], _Result],
    ) -> _Result:
        """Reserve, invoke one delegate, then persist only its evidence hash."""

        reservation = self.reserve(
            plan_sha256=plan_sha256,
            slot=slot,
            declaration=declaration,
        )
        delegate_failed = False
        try:
            result = delegate()
        except Exception:
            delegate_failed = True
        if delegate_failed:
            self._consume_failure(
                reservation,
                reason_code="read_delegate_exception",
            )
            raise Slice3ReadDelegateError("slice3_read_delegate_failed") from None
        evidence_invalid = False
        try:
            evidence_sha256 = self._evidence_sha256(result)
        except Slice3ReadJournalError:
            evidence_invalid = True
        if evidence_invalid:
            self._consume_failure(
                reservation,
                reason_code="read_evidence_invalid",
            )
            raise Slice3ReadDelegateError("slice3_read_evidence_invalid") from None
        self.consume_success(
            reservation,
            evidence_sha256=evidence_sha256,
        )
        return result

    def _is_absent(self) -> bool:
        try:
            os.lstat(self.path)
        except FileNotFoundError:
            return True
        except OSError:
            raise Slice3ReadJournalError("slice3_read_journal_unsafe") from None
        return False

    def inspect(
        self,
        *,
        plan_sha256: str,
        slot: Slice3ReadSlot,
    ) -> Slice3ReadRecord | None:
        """Return the last validated row for a plan/slot without creating it."""

        _require_sha256(
            plan_sha256,
            "slice3_read_plan_sha256_invalid",
        )
        if not isinstance(slot, Slice3ReadSlot):
            raise Slice3ReadJournalError("slice3_read_slot_invalid")
        semantic_key = _semantic_key(plan_sha256, slot)
        return self._latest_matching(self.read_all(), semantic_key)

    def read_all(self) -> list[Slice3ReadRecord]:
        """Read and fully validate the journal without creating an absent file."""

        with self._lock:
            if self._is_absent():
                return []
            descriptor = self._open()
            locked = False
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH)
                locked = True
                self._assert_descriptor_safe(descriptor)
                records = self._read_locked(descriptor)
                self._assert_descriptor_safe(descriptor)
                return records
            finally:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)


__all__ = [
    "DEFAULT_SLICE3_READ_JOURNAL_PATH",
    "SLICE3_MARGIN_FACADE_SOURCE_VECTOR",
    "SLICE3_READ_JOURNAL_PATH_ENV",
    "FileSlice3ReadJournal",
    "Slice3ReadConsumedError",
    "Slice3ReadDeclaration",
    "Slice3ReadDelegateError",
    "Slice3ReadJournalError",
    "Slice3ReadOutcome",
    "Slice3ReadRecord",
    "Slice3ReadRecordEvent",
    "configured_slice3_read_journal_path",
    "slice3_read_declaration",
]
