"""Durable, plan-independent terminal for an accepted Preview handoff.

The artifact is reserved immediately after an accepted R8, R9, or R10 Preview is
durable and before account delegation, plan construction, admission,
activation, or Coinbase-port construction.  It carries hashes only and grants
no exchange authority.  A catchable failure at any pre-orchestration boundary
turns the reservation into one immutable ``halted`` terminal without retaining
the exception.  Successful delegation is terminal too; Slice 3's separate
action and terminal journals remain the only exchange-action authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import TypeVar, cast


_REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPTED_HANDOFF_ARTIFACT_PATH = (
    _REPO_ROOT
    / "runtime_state"
    / "futures_slice3_accepted_preview_handoff_terminal.jsonl"
)
ACCEPTED_HANDOFF_AUTHORIZATION_SHA256 = (
    "5c9c2432179989446d79da2e8f173729103844a96f00e1eeec56dcf5c8e2dc51"
)
ACCEPTED_HANDOFF_PREVIEW_ARTIFACT_TYPES: Mapping[int, str] = MappingProxyType(
    {
        8: "futures_exact_no_live_preview_slice_2r8",
        9: "futures_exact_no_live_preview_slice_2r9",
        10: "futures_exact_no_live_preview_slice_2r10",
    }
)
ACCEPTED_HANDOFF_SCHEMA_VERSION = (
    "slice3-accepted-preview-handoff-terminal-record-v1"
)
ACCEPTED_HANDOFF_GENESIS_SHA256 = "0" * 64

_MAX_ARTIFACT_BYTES = 32 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESERVED_REASON = "accepted_preview_handoff_reserved"
_ROW_KEYS = frozenset(
    {
        "schema_version",
        "event",
        "recorded_at",
        "preview_generation",
        "preview_artifact_type",
        "preview_artifact_file_sha256",
        "preview_evidence_sha256",
        "authorization_sha256",
        "previous_record_sha256",
        "status",
        "stage",
        "reason_code",
        "grants_exchange_action_authority",
        "coinbase_calls_permitted",
        "raw_response_included",
        "identifier_values_included",
        "exception_text_included",
        "record_sha256",
    }
)


class AcceptedHandoffArtifactError(RuntimeError):
    """Sanitized accepted-handoff persistence or lifecycle failure."""


class AcceptedHandoffStage(str, Enum):
    """Only the five pre-orchestration boundaries that may terminalize."""

    PLAN = "plan"
    ADMISSION = "admission"
    ACTIVATION = "activation"
    PORT_CONSTRUCTION = "port_construction"
    DELEGATION = "delegation"


_HALTED_REASONS: Mapping[AcceptedHandoffStage, str] = MappingProxyType(
    {
        AcceptedHandoffStage.PLAN: "accepted_handoff_plan_failed",
        AcceptedHandoffStage.ADMISSION: "accepted_handoff_admission_failed",
        AcceptedHandoffStage.ACTIVATION: "accepted_handoff_activation_failed",
        AcceptedHandoffStage.PORT_CONSTRUCTION: (
            "accepted_handoff_port_construction_failed"
        ),
        AcceptedHandoffStage.DELEGATION: "accepted_handoff_delegation_failed",
    }
)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise AcceptedHandoffArtifactError(
            "accepted_handoff_artifact_invalid"
        ) from None


def _record_hash_payload(record: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in record.items() if key != "record_sha256"}


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AcceptedHandoffArtifactError("accepted_handoff_binding_invalid")
    return value


def _require_preview_binding(
    generation: object,
    artifact_type: object,
) -> tuple[int, str]:
    if (
        type(generation) is not int
        or not isinstance(artifact_type, str)
        or ACCEPTED_HANDOFF_PREVIEW_ARTIFACT_TYPES.get(generation)
        != artifact_type
    ):
        raise AcceptedHandoffArtifactError(
            "accepted_handoff_preview_binding_invalid"
        )
    return generation, artifact_type


def _recorded_at(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AcceptedHandoffArtifactError("accepted_handoff_time_invalid")
    return value.astimezone(timezone.utc).isoformat()


def _terminal_reason(*, status: str, stage: AcceptedHandoffStage) -> str:
    if status == "halted":
        return _HALTED_REASONS[stage]
    if status == "delegated" and stage is AcceptedHandoffStage.DELEGATION:
        return "accepted_handoff_delegated"
    raise AcceptedHandoffArtifactError("accepted_handoff_terminal_invalid")


def _build_record(
    *,
    event: str,
    recorded_at: datetime,
    preview_generation: int,
    preview_artifact_type: str,
    preview_artifact_file_sha256: str,
    preview_evidence_sha256: str,
    previous_record_sha256: str,
    status: str | None,
    stage: str,
    reason_code: str,
) -> dict[str, object]:
    generation, artifact_type = _require_preview_binding(
        preview_generation,
        preview_artifact_type,
    )
    record: dict[str, object] = {
        "schema_version": ACCEPTED_HANDOFF_SCHEMA_VERSION,
        "event": event,
        "recorded_at": _recorded_at(recorded_at),
        "preview_generation": generation,
        "preview_artifact_type": artifact_type,
        "preview_artifact_file_sha256": _require_sha256(
            preview_artifact_file_sha256
        ),
        "preview_evidence_sha256": _require_sha256(preview_evidence_sha256),
        "authorization_sha256": ACCEPTED_HANDOFF_AUTHORIZATION_SHA256,
        "previous_record_sha256": _require_sha256(previous_record_sha256),
        "status": status,
        "stage": stage,
        "reason_code": reason_code,
        "grants_exchange_action_authority": False,
        "coinbase_calls_permitted": 0,
        "raw_response_included": False,
        "identifier_values_included": False,
        "exception_text_included": False,
    }
    record["record_sha256"] = _canonical_sha256(record)
    return record


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise AcceptedHandoffArtifactError(
            "accepted_handoff_artifact_invalid"
        ) from None
    if parsed.tzinfo is None or parsed.astimezone(timezone.utc).isoformat() != value:
        raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
    return parsed


def _validate_common_row(
    row: Mapping[str, object],
    *,
    previous_record_sha256: str,
) -> None:
    if (
        frozenset(row) != _ROW_KEYS
        or row.get("schema_version") != ACCEPTED_HANDOFF_SCHEMA_VERSION
        or row.get("authorization_sha256")
        != ACCEPTED_HANDOFF_AUTHORIZATION_SHA256
        or row.get("previous_record_sha256") != previous_record_sha256
        or row.get("grants_exchange_action_authority") is not False
        or row.get("coinbase_calls_permitted") != 0
        or isinstance(row.get("coinbase_calls_permitted"), bool)
        or row.get("raw_response_included") is not False
        or row.get("identifier_values_included") is not False
        or row.get("exception_text_included") is not False
    ):
        raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
    _timestamp(row.get("recorded_at"))
    _require_preview_binding(
        row.get("preview_generation"),
        row.get("preview_artifact_type"),
    )
    _require_sha256(row.get("preview_artifact_file_sha256"))
    _require_sha256(row.get("preview_evidence_sha256"))
    record_sha256 = _require_sha256(row.get("record_sha256"))
    if _canonical_sha256(_record_hash_payload(row)) != record_sha256:
        raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")


def _decode_rows(raw: bytes) -> list[dict[str, object]]:
    if not raw or len(raw) > _MAX_ARTIFACT_BYTES or not raw.endswith(b"\n"):
        raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise AcceptedHandoffArtifactError(
            "accepted_handoff_artifact_invalid"
        ) from None
    if len(lines) not in (1, 2):
        raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
    rows: list[dict[str, object]] = []
    previous = ACCEPTED_HANDOFF_GENESIS_SHA256
    for line in lines:
        try:
            parsed = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_invalid"
            ) from None
        if (
            not isinstance(parsed, dict)
            or _canonical_bytes(parsed).decode("utf-8") != line
        ):
            raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
        row = cast(dict[str, object], parsed)
        _validate_common_row(row, previous_record_sha256=previous)
        previous = cast(str, row["record_sha256"])
        rows.append(row)

    reservation = rows[0]
    if (
        reservation.get("event") != "accepted_handoff_reserved"
        or reservation.get("status") is not None
        or reservation.get("stage") != "reservation"
        or reservation.get("reason_code") != _RESERVED_REASON
    ):
        raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
    if len(rows) == 2:
        terminal = rows[1]
        try:
            stage = AcceptedHandoffStage(cast(str, terminal.get("stage")))
        except (TypeError, ValueError):
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_invalid"
            ) from None
        status = terminal.get("status")
        if (
            terminal.get("event") != "terminal"
            or status not in {"halted", "delegated"}
            or terminal.get("reason_code")
            != _terminal_reason(status=cast(str, status), stage=stage)
            or terminal.get("preview_generation")
            != reservation.get("preview_generation")
            or terminal.get("preview_artifact_type")
            != reservation.get("preview_artifact_type")
            or terminal.get("preview_artifact_file_sha256")
            != reservation.get("preview_artifact_file_sha256")
            or terminal.get("preview_evidence_sha256")
            != reservation.get("preview_evidence_sha256")
            or _timestamp(terminal.get("recorded_at"))
            < _timestamp(reservation.get("recorded_at"))
        ):
            raise AcceptedHandoffArtifactError("accepted_handoff_artifact_invalid")
    return rows


@dataclass(slots=True)
class AcceptedHandoffLease:
    """Process-held lock for one reserved accepted-Preview handoff."""

    descriptor: int
    preview_generation: int
    preview_artifact_type: str
    preview_artifact_file_sha256: str
    preview_evidence_sha256: str
    recovered: bool
    _store_token: object = field(repr=False)
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self.descriptor)
        except OSError:
            pass


@dataclass(frozen=True, slots=True)
class AcceptedHandoffTerminalResult:
    """Strict sanitized readback of the immutable full-file terminal."""

    status: str
    stage: str
    reason_code: str
    artifact_sha256: str
    preview_generation: int
    preview_artifact_type: str
    preview_artifact_file_sha256: str
    preview_evidence_sha256: str


class FileAcceptedHandoffArtifactStore:
    """Owner-only, one-use JSONL store with atomic terminal replacement."""

    def __init__(self, path: Path | str | None = None) -> None:
        selected = ACCEPTED_HANDOFF_ARTIFACT_PATH if path is None else Path(path)
        self.path = Path(os.path.abspath(selected))
        self._store_token = object()

    def _ensure_safe_parent(self) -> None:
        try:
            parent = self.path.parent
            direct = os.lstat(parent)
            if (
                stat.S_ISLNK(direct.st_mode)
                or not stat.S_ISDIR(direct.st_mode)
                or direct.st_uid != os.geteuid()
                or stat.S_IMODE(direct.st_mode) & 0o022
            ):
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_artifact_unsafe"
                )
            for component in (parent, *parent.parents):
                metadata = os.lstat(component)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
                    metadata.st_mode
                ):
                    raise AcceptedHandoffArtifactError(
                        "accepted_handoff_artifact_unsafe"
                    )
        except AcceptedHandoffArtifactError:
            raise
        except OSError:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_unsafe"
            ) from None

    def _open_parent(self) -> int:
        try:
            descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return descriptor
        except BlockingIOError:
            if "descriptor" in locals():
                os.close(descriptor)
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_attempt_consumed"
            ) from None
        except OSError:
            if "descriptor" in locals():
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_unsafe"
            ) from None

    @staticmethod
    def _close_parent(descriptor: int | None) -> None:
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(descriptor)
        except OSError:
            pass

    @staticmethod
    def _metadata_safe(metadata: os.stat_result, *, mode: int) -> bool:
        return bool(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
            and stat.S_IMODE(metadata.st_mode) == mode
            and metadata.st_nlink == 1
            and 0 < metadata.st_size <= _MAX_ARTIFACT_BYTES
        )

    def _assert_bound(self, descriptor: int, *, mode: int) -> None:
        try:
            opened = os.fstat(descriptor)
            linked = os.lstat(self.path)
        except OSError:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_unsafe"
            ) from None
        if (
            not self._metadata_safe(opened, mode=mode)
            or not self._metadata_safe(linked, mode=mode)
            or stat.S_ISLNK(linked.st_mode)
            or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
        ):
            raise AcceptedHandoffArtifactError("accepted_handoff_artifact_unsafe")

    @staticmethod
    def _read_descriptor(descriptor: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        return os.read(descriptor, _MAX_ARTIFACT_BYTES + 1)

    def reserve(
        self,
        *,
        preview_generation: int,
        preview_artifact_type: str,
        preview_artifact_file_sha256: str,
        preview_evidence_sha256: str,
        now: datetime,
    ) -> AcceptedHandoffLease:
        """Create the first row, or safely recover its matching open lease."""

        generation, artifact_type = _require_preview_binding(
            preview_generation,
            preview_artifact_type,
        )
        file_sha256 = _require_sha256(preview_artifact_file_sha256)
        evidence_sha256 = _require_sha256(preview_evidence_sha256)
        reservation = _build_record(
            event="accepted_handoff_reserved",
            recorded_at=now,
            preview_generation=generation,
            preview_artifact_type=artifact_type,
            preview_artifact_file_sha256=file_sha256,
            preview_evidence_sha256=evidence_sha256,
            previous_record_sha256=ACCEPTED_HANDOFF_GENESIS_SHA256,
            status=None,
            stage="reservation",
            reason_code=_RESERVED_REASON,
        )
        payload = _canonical_bytes(reservation) + b"\n"
        self._ensure_safe_parent()
        parent: int | None = None
        descriptor: int | None = None
        try:
            parent = self._open_parent()
            try:
                existing = os.lstat(self.path)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                mode = stat.S_IMODE(existing.st_mode)
                if (
                    stat.S_ISLNK(existing.st_mode)
                    or not stat.S_ISREG(existing.st_mode)
                    or existing.st_uid != os.geteuid()
                    or existing.st_nlink != 1
                    or mode not in {0o400, 0o600}
                ):
                    raise AcceptedHandoffArtifactError(
                        "accepted_handoff_artifact_unsafe"
                    )
                flags = os.O_RDONLY if mode == 0o400 else os.O_RDWR
                descriptor = os.open(self.path, flags | _NOFOLLOW | _CLOEXEC)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AcceptedHandoffArtifactError(
                        "accepted_handoff_attempt_consumed"
                    ) from None
                self._assert_bound(descriptor, mode=mode)
                rows = _decode_rows(self._read_descriptor(descriptor))
                if mode == 0o400:
                    if len(rows) != 2:
                        raise AcceptedHandoffArtifactError(
                            "accepted_handoff_artifact_invalid"
                        )
                    raise AcceptedHandoffArtifactError(
                        "accepted_handoff_attempt_consumed"
                    )
                if len(rows) != 1:
                    raise AcceptedHandoffArtifactError(
                        "accepted_handoff_artifact_invalid"
                    )
                reserved = rows[0]
                if (
                    reserved.get("preview_generation") != generation
                    or reserved.get("preview_artifact_type") != artifact_type
                    or reserved.get("preview_artifact_file_sha256")
                    != file_sha256
                    or reserved.get("preview_evidence_sha256")
                    != evidence_sha256
                ):
                    raise AcceptedHandoffArtifactError(
                        "accepted_handoff_binding_invalid"
                    )
                lease = AcceptedHandoffLease(
                    descriptor=descriptor,
                    preview_generation=generation,
                    preview_artifact_type=artifact_type,
                    preview_artifact_file_sha256=file_sha256,
                    preview_evidence_sha256=evidence_sha256,
                    recovered=True,
                    _store_token=self._store_token,
                )
                descriptor = None
                return lease

            descriptor = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                0o600,
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            self._assert_bound(descriptor, mode=0o600)
            os.fsync(parent)
            lease = AcceptedHandoffLease(
                descriptor=descriptor,
                preview_generation=generation,
                preview_artifact_type=artifact_type,
                preview_artifact_file_sha256=file_sha256,
                preview_evidence_sha256=evidence_sha256,
                recovered=False,
                _store_token=self._store_token,
            )
            descriptor = None
            return lease
        except AcceptedHandoffArtifactError:
            raise
        except FileExistsError:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_attempt_consumed"
            ) from None
        except OSError:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_write_failed"
            ) from None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            self._close_parent(parent)

    def _complete(
        self,
        *,
        lease: AcceptedHandoffLease,
        status: str,
        stage: AcceptedHandoffStage,
        now: datetime,
    ) -> str:
        if (
            not isinstance(lease, AcceptedHandoffLease)
            or lease.released
            or lease._store_token is not self._store_token
            or not isinstance(stage, AcceptedHandoffStage)
        ):
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_attempt_lease_invalid"
            )
        reason = _terminal_reason(status=status, stage=stage)
        parent: int | None = None
        temp_descriptor: int | None = None
        temp_path = self.path.with_name(f".{self.path.name}.terminal.tmp")
        temp_identity: tuple[int, int] | None = None
        completed = b""
        try:
            parent = self._open_parent()
            self._assert_bound(lease.descriptor, mode=0o600)
            rows = _decode_rows(self._read_descriptor(lease.descriptor))
            if len(rows) != 1:
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_terminal_already_completed"
                )
            reservation = rows[0]
            if (
                reservation.get("preview_generation")
                != lease.preview_generation
                or reservation.get("preview_artifact_type")
                != lease.preview_artifact_type
                or reservation.get("preview_artifact_file_sha256")
                != lease.preview_artifact_file_sha256
                or reservation.get("preview_evidence_sha256")
                != lease.preview_evidence_sha256
            ):
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_binding_invalid"
                )
            if _timestamp(_recorded_at(now)) < _timestamp(
                reservation.get("recorded_at")
            ):
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_time_invalid"
                )
            terminal = _build_record(
                event="terminal",
                recorded_at=now,
                preview_generation=lease.preview_generation,
                preview_artifact_type=lease.preview_artifact_type,
                preview_artifact_file_sha256=(
                    lease.preview_artifact_file_sha256
                ),
                preview_evidence_sha256=lease.preview_evidence_sha256,
                previous_record_sha256=cast(str, reservation["record_sha256"]),
                status=status,
                stage=stage.value,
                reason_code=reason,
            )
            completed = (
                _canonical_bytes(reservation)
                + b"\n"
                + _canonical_bytes(terminal)
                + b"\n"
            )
            if len(completed) > _MAX_ARTIFACT_BYTES:
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_artifact_invalid"
                )
            temp_descriptor = os.open(
                temp_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                0o600,
            )
            os.fchmod(temp_descriptor, 0o600)
            _write_all(temp_descriptor, completed)
            os.fsync(temp_descriptor)
            os.fchmod(temp_descriptor, 0o400)
            os.fsync(temp_descriptor)
            opened_temp = os.fstat(temp_descriptor)
            linked_temp = os.lstat(temp_path)
            temp_identity = (opened_temp.st_dev, opened_temp.st_ino)
            if (
                not self._metadata_safe(opened_temp, mode=0o400)
                or not self._metadata_safe(linked_temp, mode=0o400)
                or temp_identity != (linked_temp.st_dev, linked_temp.st_ino)
            ):
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_artifact_unsafe"
                )
            self._assert_bound(lease.descriptor, mode=0o600)
            os.replace(
                temp_path.name,
                self.path.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            os.fsync(parent)
            linked_final = os.lstat(self.path)
            if (
                not self._metadata_safe(linked_final, mode=0o400)
                or temp_identity != (linked_final.st_dev, linked_final.st_ino)
            ):
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_artifact_unsafe"
                )
            os.lseek(temp_descriptor, 0, os.SEEK_SET)
            final_bytes = os.read(temp_descriptor, _MAX_ARTIFACT_BYTES + 1)
            if final_bytes != completed or len(_decode_rows(final_bytes)) != 2:
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_artifact_invalid"
                )
            return hashlib.sha256(completed).hexdigest()
        except AcceptedHandoffArtifactError:
            raise
        except FileExistsError:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_unsafe"
            ) from None
        except OSError:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_write_failed"
            ) from None
        finally:
            if temp_descriptor is not None:
                try:
                    os.close(temp_descriptor)
                except OSError:
                    pass
            try:
                leftover = os.lstat(temp_path)
            except FileNotFoundError:
                leftover = None
            except OSError:
                leftover = None
            if (
                leftover is not None
                and temp_identity == (leftover.st_dev, leftover.st_ino)
            ):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            lease.release()
            self._close_parent(parent)

    def complete_halted(
        self,
        *,
        lease: AcceptedHandoffLease,
        stage: AcceptedHandoffStage,
        now: datetime,
    ) -> str:
        return self._complete(
            lease=lease,
            status="halted",
            stage=stage,
            now=now,
        )

    def complete_delegated(
        self,
        *,
        lease: AcceptedHandoffLease,
        now: datetime,
    ) -> str:
        return self._complete(
            lease=lease,
            status="delegated",
            stage=AcceptedHandoffStage.DELEGATION,
            now=now,
        )

    def _read_terminal_payload(self) -> tuple[dict[str, object], bytes]:
        self._ensure_safe_parent()
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, os.O_RDONLY | _NOFOLLOW | _CLOEXEC)
            self._assert_bound(descriptor, mode=0o400)
            raw = self._read_descriptor(descriptor)
            rows = _decode_rows(raw)
            if len(rows) != 2:
                raise AcceptedHandoffArtifactError(
                    "accepted_handoff_artifact_invalid"
                )
            return dict(rows[1]), raw
        except AcceptedHandoffArtifactError:
            raise
        except OSError:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_artifact_unsafe"
            ) from None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def read_terminal(self) -> Mapping[str, object]:
        """Return the validated terminal row without changing the artifact."""

        terminal, _raw = self._read_terminal_payload()
        return MappingProxyType(terminal)

    def read_terminal_result(self) -> AcceptedHandoffTerminalResult:
        """Return only allowlisted atoms plus the bound full-file SHA-256."""

        terminal, raw = self._read_terminal_payload()
        return AcceptedHandoffTerminalResult(
            status=cast(str, terminal["status"]),
            stage=cast(str, terminal["stage"]),
            reason_code=cast(str, terminal["reason_code"]),
            artifact_sha256=hashlib.sha256(raw).hexdigest(),
            preview_generation=cast(int, terminal["preview_generation"]),
            preview_artifact_type=cast(str, terminal["preview_artifact_type"]),
            preview_artifact_file_sha256=cast(
                str,
                terminal["preview_artifact_file_sha256"],
            ),
            preview_evidence_sha256=cast(
                str,
                terminal["preview_evidence_sha256"],
            ),
        )


_T = TypeVar("_T")


class AcceptedHandoffTerminalizer:
    """Run allowlisted boundaries and terminalize without exception content."""

    def __init__(
        self,
        *,
        store: FileAcceptedHandoffArtifactStore,
        lease: AcceptedHandoffLease,
    ) -> None:
        self.store = store
        self.lease = lease
        self._completed = False

    @staticmethod
    def _now(provider: Callable[[], datetime] | None) -> datetime:
        if provider is not None:
            try:
                supplied = provider()
                if isinstance(supplied, datetime) and supplied.tzinfo is not None:
                    return supplied
            except BaseException:
                pass
        return datetime.now(timezone.utc)

    def _require_open(self) -> None:
        if self._completed or self.lease.released:
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_terminal_already_completed"
            )

    @property
    def completed(self) -> bool:
        """Whether this in-memory capability has written its terminal row."""

        return self._completed

    def call(
        self,
        stage: AcceptedHandoffStage,
        operation: Callable[[], _T],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> _T:
        """Run one boundary; a failure becomes the sole halted terminal."""

        self._require_open()
        if not isinstance(stage, AcceptedHandoffStage) or not callable(operation):
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_boundary_invalid"
            )
        try:
            return operation()
        except BaseException:
            self.store.complete_halted(
                lease=self.lease,
                stage=stage,
                now=self._now(now),
            )
            self._completed = True
            raise

    def delegate(
        self,
        operation: Callable[[], _T],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> _T:
        """Terminalize either successful or failed orchestration delegation."""

        self._require_open()
        if not callable(operation):
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_boundary_invalid"
            )
        try:
            result = operation()
        except BaseException:
            # A nested port-construction boundary may already have written the
            # sole halted terminal.  Preserve that earlier, more exact stage.
            if not self._completed and not self.lease.released:
                self.store.complete_halted(
                    lease=self.lease,
                    stage=AcceptedHandoffStage.DELEGATION,
                    now=self._now(now),
                )
                self._completed = True
            raise
        self.store.complete_delegated(
            lease=self.lease,
            now=self._now(now),
        )
        self._completed = True
        return result


def halt_accepted_preview_handoff_offline(
    *,
    path: Path | str,
    preview_generation: int,
    preview_artifact_type: str,
    preview_artifact_file_sha256: str,
    preview_evidence_sha256: str,
    now: datetime,
) -> AcceptedHandoffTerminalResult:
    """Recover or create the hash-only reservation, then halt without I/O ports.

    The caller must first validate that the matching sanitized Preview artifact
    is accepted.  This helper knows no credentials, Preview client, Coinbase
    delegate, action journal, or exchange port, so it cannot retry or mutate.
    """

    generation, artifact_type = _require_preview_binding(
        preview_generation,
        preview_artifact_type,
    )
    file_sha256 = _require_sha256(preview_artifact_file_sha256)
    evidence_sha256 = _require_sha256(preview_evidence_sha256)
    store = FileAcceptedHandoffArtifactStore(path)
    try:
        lease = store.reserve(
            preview_generation=generation,
            preview_artifact_type=artifact_type,
            preview_artifact_file_sha256=file_sha256,
            preview_evidence_sha256=evidence_sha256,
            now=now,
        )
    except AcceptedHandoffArtifactError as exc:
        if str(exc) != "accepted_handoff_attempt_consumed":
            raise
        existing = store.read_terminal_result()
        if (
            existing.status != "halted"
            or existing.preview_generation != generation
            or existing.preview_artifact_type != artifact_type
            or existing.preview_artifact_file_sha256 != file_sha256
            or existing.preview_evidence_sha256 != evidence_sha256
        ):
            raise AcceptedHandoffArtifactError(
                "accepted_handoff_binding_invalid"
            ) from None
        return existing
    store.complete_halted(
        lease=lease,
        stage=AcceptedHandoffStage.DELEGATION,
        now=now,
    )
    return store.read_terminal_result()


__all__ = [
    "ACCEPTED_HANDOFF_ARTIFACT_PATH",
    "ACCEPTED_HANDOFF_AUTHORIZATION_SHA256",
    "ACCEPTED_HANDOFF_PREVIEW_ARTIFACT_TYPES",
    "AcceptedHandoffArtifactError",
    "AcceptedHandoffLease",
    "AcceptedHandoffStage",
    "AcceptedHandoffTerminalResult",
    "AcceptedHandoffTerminalizer",
    "FileAcceptedHandoffArtifactStore",
    "halt_accepted_preview_handoff_offline",
]
