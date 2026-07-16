"""Finite, one-use composition for the sealed Slice 3 roundtrip.

The orchestrator owns no credential lookup and constructs no Coinbase client
on its own.  It composes an already-sealed activation, the durable action and
read journals, and one injected strict port.  Every exchange-facing operation
has one statically selected boundary; there is no polling, retry, fallback, or
redirect path in this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Protocol, cast

from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_LIVE_POLICY,
    SLICE3_MAX_READ_AGE,
    SLICE3_PRODUCT_ID,
    FileSlice3ActionClaimStore,
    Slice3ActionKind,
    Slice3ClaimEvent,
    Slice3Directive,
    Slice3DirectiveKind,
    Slice3MarketReference,
    Slice3MutationGate,
    Slice3MutationOutcome,
    Slice3MutationResult,
    Slice3OpenOrderZeroProof,
    Slice3OrderResolutionSource,
    Slice3Plan,
    Slice3PositionObservation,
    Slice3PreCreateEvidence,
    Slice3ReadSlot,
    decide_slice3_next_action,
)
from application.admin_api.futures_terminal_roundtrip_activation import (
    Slice3ActivationSeal,
)
from application.admin_api.futures_terminal_roundtrip_admission import (
    SLICE3_ADMISSION_ARTIFACT_PATH,
    Slice3AdmissionSeal,
    production_slice3_admission_store,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3ExactOrderEvidence,
    Slice3MarginSummary,
)
from application.admin_api.futures_terminal_roundtrip_reads import (
    FileSlice3ReadJournal,
    Slice3ReadOutcome,
    Slice3ReadRecordEvent,
    slice3_read_declaration,
)
from application.admin_api.futures_terminal_roundtrip_terminal import (
    Slice3ActionTerminalBinding,
    Slice3HaltedReconciliationEvidence,
    Slice3TerminalRoundtripEvidence,
)
from core.enums import OrderSide, OrderStatus


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REASON = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")
_TERMINAL_GENESIS_SHA256 = "0" * 64
_TERMINAL_RECORD_SCHEMA_VERSION = "slice3-terminal-artifact-record-v1"
_MAX_TERMINAL_ARTIFACT_BYTES = 256 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

_SCHEMA_VERSIONS = {
    "action_journal": "slice3-action-claim-record-v4",
    "read_journal": "slice3-read-journal-record-v1",
    "terminal_evidence": "slice3-terminal-roundtrip-evidence-v2",
    "slice3_live_policy": "slice3-terminal-roundtrip-policy-v1",
}
_ATTEMPT_LIMITS = {
    "preview": 0,
    "create": 1,
    "cancel": 1,
    "close": 1,
    "reduce": 0,
    "retry": 0,
    "fallback": 0,
    "redirect": 0,
}


class Slice3OrchestrationError(RuntimeError):
    """Sanitized failure that occurs outside a completed terminal result."""


class Slice3TerminalArtifactError(Slice3OrchestrationError):
    """Raised when the one-use terminal artifact is consumed or unsafe."""


class Slice3OrchestrationStatus(str, Enum):
    """Only two durable terminal classifications."""

    RESTORED_BASELINE = "restored_baseline"
    HALTED = "halted"


@dataclass(frozen=True)
class Slice3OrchestrationResult:
    """Sanitized result returned after the terminal artifact is immutable."""

    status: Slice3OrchestrationStatus
    terminal_evidence: (
        Slice3TerminalRoundtripEvidence | Slice3HaltedReconciliationEvidence
    )
    reason_code: str
    terminal_artifact_sha256: str


class _ActivationStore(Protocol):
    def read(
        self,
        *,
        now: datetime,
        expected_manifest_sha256: str,
    ) -> Slice3ActivationSeal: ...


class _AdmissionStore(Protocol):
    path: Path

    def read(
        self,
        *,
        now: datetime,
        expected_chain_sha256: str,
    ) -> Slice3AdmissionSeal: ...


class _Slice3Port(Protocol):
    def create_order(self, **kwargs: object) -> Slice3MutationResult: ...

    def cancel_order(self, **kwargs: object) -> Slice3MutationResult: ...

    def close_position(self, **kwargs: object) -> Slice3MutationResult: ...

    def prove_zero_open_orders(
        self,
        *,
        observed_at: datetime,
    ) -> Slice3OpenOrderZeroProof: ...

    def read_position(
        self,
        *,
        observed_at: datetime,
    ) -> Slice3PositionObservation: ...

    def read_exact_order(self, **kwargs: object) -> Slice3ExactOrderEvidence: ...

    def resolve_exact_order_by_client_order_id(
        self,
        **kwargs: object,
    ) -> Slice3ExactOrderEvidence: ...

    def resolve_exact_close_order_by_client_order_id(
        self,
        **kwargs: object,
    ) -> Slice3ExactOrderEvidence: ...

    def read_market_reference(
        self,
        *,
        observed_at: datetime,
    ) -> Slice3MarketReference: ...

    def read_margin_summary(
        self,
        *,
        observed_at: datetime,
    ) -> Slice3MarginSummary: ...


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
        raise Slice3OrchestrationError(
            "slice3_terminal_canonical_json_invalid"
        ) from None


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _runtime_file_sha256(filename: str) -> str:
    """Hash one stable, owner-controlled Slice 3 source file by raw bytes."""

    path = Path(__file__).with_name(filename)
    descriptor: int | None = None
    try:
        linked_before = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(linked_before.st_mode)
            or linked_before.st_uid != os.geteuid()
            or linked_before.st_nlink != 1
        ):
            raise OSError
        descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW | _CLOEXEC)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or opened.st_dev != linked_before.st_dev
            or opened.st_ino != linked_before.st_ino
        ):
            raise OSError
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        opened_after = os.fstat(descriptor)
        linked_after = os.stat(path, follow_symlinks=False)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(
            getattr(opened, field) != getattr(opened_after, field)
            or getattr(opened, field) != getattr(linked_after, field)
            for field in stable_fields
        ):
            raise OSError
        return hashlib.sha256(b"".join(chunks)).hexdigest()
    except (OSError, ValueError):
        raise Slice3OrchestrationError(
            "slice3_activation_runtime_hash_unavailable"
        ) from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _require_sha256(value: object, reason: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Slice3OrchestrationError(reason)
    return value


def _require_reason(value: object) -> str:
    if not isinstance(value, str) or _REASON.fullmatch(value) is None:
        raise Slice3OrchestrationError("slice3_terminal_reason_invalid")
    return value


def _aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise Slice3OrchestrationError("slice3_orchestration_time_invalid")
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise Slice3OrchestrationError("slice3_orchestration_time_invalid") from None


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(descriptor, payload[offset:])
        except OSError:
            written = 0
        if written <= 0:
            raise Slice3TerminalArtifactError("slice3_terminal_artifact_write_failed")
        offset += written


def _record_hash_payload(record: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in record.items() if key != "record_sha256"}


def _record(
    *,
    event: str,
    recorded_at: datetime,
    plan_sha256: str,
    activation_manifest_sha256: str,
    previous_record_sha256: str,
    status: str | None,
    reason_code: str,
    phase: str,
    terminal_evidence: Mapping[str, object] | None,
    action_journal_sha256: str | None,
    read_journal_sha256: str | None,
) -> dict[str, object]:
    provisional: dict[str, object] = {
        "schema_version": _TERMINAL_RECORD_SCHEMA_VERSION,
        "event": event,
        "recorded_at": _aware_utc(recorded_at).isoformat(),
        "plan_sha256": _require_sha256(
            plan_sha256,
            "slice3_terminal_plan_sha256_invalid",
        ),
        "activation_manifest_sha256": _require_sha256(
            activation_manifest_sha256,
            "slice3_terminal_activation_sha256_invalid",
        ),
        "status": status,
        "reason_code": _require_reason(reason_code),
        "phase": _require_reason(phase),
        "terminal_evidence": (
            None if terminal_evidence is None else dict(terminal_evidence)
        ),
        "action_journal_sha256": action_journal_sha256,
        "read_journal_sha256": read_journal_sha256,
        "raw_response_included": False,
        "identifier_values_included": False,
        "exception_text_included": False,
        "previous_record_sha256": _require_sha256(
            previous_record_sha256,
            "slice3_terminal_previous_sha256_invalid",
        ),
        "record_sha256": _TERMINAL_GENESIS_SHA256,
    }
    for digest in (action_journal_sha256, read_journal_sha256):
        if digest is not None:
            _require_sha256(digest, "slice3_terminal_journal_sha256_invalid")
    provisional["record_sha256"] = _canonical_sha256(_record_hash_payload(provisional))
    return provisional


@dataclass
class Slice3TerminalAttemptLease:
    """Process-held exclusive lease for one new or interrupted attempt."""

    descriptor: int
    recovered: bool
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


class FileSlice3TerminalArtifactStore:
    """Exclusive-create, two-row, owner-only terminal artifact."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(
            path
            if path is not None
            else Path("runtime_state/futures_slice3_terminal_evidence.json")
        )

    def _ensure_safe_parent(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            parent = Path(os.path.abspath(self.path.parent))
            for component in reversed((parent, *parent.parents)):
                metadata = os.lstat(component)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise Slice3TerminalArtifactError("slice3_terminal_artifact_unsafe")
        except Slice3TerminalArtifactError:
            raise
        except OSError:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_artifact_unsafe"
            ) from None

    def _fsync_parent(self) -> None:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            )
            os.fsync(descriptor)
        except OSError:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_artifact_write_failed"
            ) from None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _acquire_parent_guard(self) -> int:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return descriptor
        except BlockingIOError:
            if descriptor is not None:
                os.close(descriptor)
            raise Slice3TerminalArtifactError(
                "slice3_terminal_attempt_consumed"
            ) from None
        except OSError:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise Slice3TerminalArtifactError(
                "slice3_terminal_artifact_unsafe"
            ) from None

    @staticmethod
    def _release_parent_guard(descriptor: int | None) -> None:
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
            and metadata.st_uid == os.getuid()
            and stat.S_IMODE(metadata.st_mode) == mode
            and metadata.st_nlink == 1
            and 0 < metadata.st_size <= _MAX_TERMINAL_ARTIFACT_BYTES
        )

    def _assert_bound_metadata(self, descriptor: int, *, mode: int) -> None:
        try:
            opened = os.fstat(descriptor)
            path = os.lstat(self.path)
        except OSError:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_artifact_unsafe"
            ) from None
        if (
            not self._metadata_safe(opened, mode=mode)
            or not self._metadata_safe(path, mode=mode)
            or stat.S_ISLNK(path.st_mode)
            or opened.st_dev != path.st_dev
            or opened.st_ino != path.st_ino
        ):
            raise Slice3TerminalArtifactError("slice3_terminal_artifact_unsafe")

    @staticmethod
    def _decode_rows(raw: bytes) -> list[dict[str, object]]:
        if (
            not raw
            or len(raw) > _MAX_TERMINAL_ARTIFACT_BYTES
            or not raw.endswith(b"\n")
        ):
            raise Slice3TerminalArtifactError("slice3_terminal_artifact_invalid")
        rows: list[dict[str, object]] = []
        previous = _TERMINAL_GENESIS_SHA256
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_artifact_invalid"
            ) from None
        for line in lines:
            try:
                value = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                raise Slice3TerminalArtifactError(
                    "slice3_terminal_artifact_invalid"
                ) from None
            if (
                not isinstance(value, dict)
                or _canonical_bytes(value).decode("utf-8") != line
            ):
                raise Slice3TerminalArtifactError("slice3_terminal_artifact_invalid")
            record_sha256 = value.get("record_sha256")
            if (
                value.get("schema_version") != _TERMINAL_RECORD_SCHEMA_VERSION
                or value.get("previous_record_sha256") != previous
                or not isinstance(record_sha256, str)
                or _canonical_sha256(_record_hash_payload(value)) != record_sha256
            ):
                raise Slice3TerminalArtifactError("slice3_terminal_artifact_invalid")
            previous = record_sha256
            rows.append(cast(dict[str, object], value))
        return rows

    def reserve(
        self,
        *,
        plan_sha256: str,
        activation_manifest_sha256: str,
        now: datetime,
    ) -> Slice3TerminalAttemptLease:
        """Lock a new attempt or a crash-left one-row reservation."""

        self._ensure_safe_parent()
        attempt = _record(
            event="attempt_reserved",
            recorded_at=now,
            plan_sha256=plan_sha256,
            activation_manifest_sha256=activation_manifest_sha256,
            previous_record_sha256=_TERMINAL_GENESIS_SHA256,
            status=None,
            reason_code="orchestration_attempt_reserved",
            phase="reservation",
            terminal_evidence=None,
            action_journal_sha256=None,
            read_journal_sha256=None,
        )
        descriptor: int | None = None
        parent_guard: int | None = None
        try:
            parent_guard = self._acquire_parent_guard()
            try:
                existing = os.lstat(self.path)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if (
                    stat.S_ISLNK(existing.st_mode)
                    or not stat.S_ISREG(existing.st_mode)
                    or existing.st_uid != os.getuid()
                    or existing.st_nlink != 1
                ):
                    raise Slice3TerminalArtifactError("slice3_terminal_artifact_unsafe")
                if stat.S_IMODE(existing.st_mode) == 0o400:
                    raise Slice3TerminalArtifactError(
                        "slice3_terminal_attempt_consumed"
                    )
                if stat.S_IMODE(existing.st_mode) != 0o600:
                    raise Slice3TerminalArtifactError("slice3_terminal_artifact_unsafe")
                descriptor = os.open(
                    self.path,
                    os.O_RDWR | _NOFOLLOW | _CLOEXEC,
                )
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Slice3TerminalArtifactError(
                        "slice3_terminal_attempt_consumed"
                    ) from None
                self._assert_bound_metadata(descriptor, mode=0o600)
                os.lseek(descriptor, 0, os.SEEK_SET)
                rows = self._decode_rows(
                    os.read(descriptor, _MAX_TERMINAL_ARTIFACT_BYTES + 1)
                )
                if len(rows) == 2:
                    os.fchmod(descriptor, 0o400)
                    os.fsync(descriptor)
                    raise Slice3TerminalArtifactError(
                        "slice3_terminal_attempt_consumed"
                    )
                if len(rows) != 1:
                    raise Slice3TerminalArtifactError(
                        "slice3_terminal_artifact_invalid"
                    )
                reserved = rows[0]
                if (
                    reserved.get("event") != "attempt_reserved"
                    or reserved.get("plan_sha256") != plan_sha256
                    or reserved.get("activation_manifest_sha256")
                    != activation_manifest_sha256
                ):
                    raise Slice3TerminalArtifactError(
                        "slice3_terminal_artifact_binding_invalid"
                    )
                lease = Slice3TerminalAttemptLease(
                    descriptor=descriptor,
                    recovered=True,
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
            _write_all(descriptor, _canonical_bytes(attempt) + b"\n")
            os.fsync(descriptor)
            self._assert_bound_metadata(descriptor, mode=0o600)
            self._fsync_parent()
            lease = Slice3TerminalAttemptLease(
                descriptor=descriptor,
                recovered=False,
            )
            descriptor = None
            return lease
        except Slice3TerminalArtifactError:
            raise
        except FileExistsError:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_attempt_consumed"
            ) from None
        except OSError:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_artifact_write_failed"
            ) from None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            self._release_parent_guard(parent_guard)

    def _complete(
        self,
        *,
        lease: Slice3TerminalAttemptLease,
        plan_sha256: str,
        activation_manifest_sha256: str,
        now: datetime,
        status: Slice3OrchestrationStatus,
        reason_code: str,
        phase: str,
        terminal_evidence: Mapping[str, object] | None,
        action_journal_sha256: str,
        read_journal_sha256: str,
    ) -> str:
        if not isinstance(lease, Slice3TerminalAttemptLease) or lease.released:
            raise Slice3TerminalArtifactError("slice3_terminal_attempt_lease_invalid")
        descriptor = lease.descriptor
        completed = b""
        try:
            self._assert_bound_metadata(descriptor, mode=0o600)
            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = os.read(descriptor, _MAX_TERMINAL_ARTIFACT_BYTES + 1)
            rows = self._decode_rows(raw)
            if len(rows) != 1:
                raise Slice3TerminalArtifactError(
                    "slice3_terminal_artifact_already_completed"
                )
            attempt = rows[0]
            if (
                attempt.get("event") != "attempt_reserved"
                or attempt.get("plan_sha256") != plan_sha256
                or attempt.get("activation_manifest_sha256")
                != activation_manifest_sha256
            ):
                raise Slice3TerminalArtifactError(
                    "slice3_terminal_artifact_binding_invalid"
                )
            previous = cast(str, attempt["record_sha256"])
            completion = _record(
                event="terminal",
                recorded_at=now,
                plan_sha256=plan_sha256,
                activation_manifest_sha256=activation_manifest_sha256,
                previous_record_sha256=previous,
                status=status.value,
                reason_code=reason_code,
                phase=phase,
                terminal_evidence=terminal_evidence,
                action_journal_sha256=action_journal_sha256,
                read_journal_sha256=read_journal_sha256,
            )
            os.lseek(descriptor, 0, os.SEEK_END)
            _write_all(descriptor, _canonical_bytes(completion) + b"\n")
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            self._assert_bound_metadata(descriptor, mode=0o400)
            os.lseek(descriptor, 0, os.SEEK_SET)
            completed = os.read(descriptor, _MAX_TERMINAL_ARTIFACT_BYTES + 1)
            completed_rows = self._decode_rows(completed)
            if len(completed_rows) != 2:
                raise Slice3TerminalArtifactError("slice3_terminal_artifact_invalid")
        except Slice3TerminalArtifactError:
            raise
        except OSError:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_artifact_write_failed"
            ) from None
        finally:
            lease.release()
        self._fsync_parent()
        return hashlib.sha256(completed).hexdigest()

    def complete_restored(
        self,
        *,
        lease: Slice3TerminalAttemptLease,
        plan_sha256: str,
        activation_manifest_sha256: str,
        now: datetime,
        evidence: Slice3TerminalRoundtripEvidence,
        action_journal_sha256: str,
        read_journal_sha256: str,
    ) -> str:
        return self._complete(
            lease=lease,
            plan_sha256=plan_sha256,
            activation_manifest_sha256=activation_manifest_sha256,
            now=now,
            status=Slice3OrchestrationStatus.RESTORED_BASELINE,
            reason_code="restored_baseline",
            phase="complete",
            terminal_evidence=cast(Mapping[str, object], evidence.sanitized_evidence()),
            action_journal_sha256=action_journal_sha256,
            read_journal_sha256=read_journal_sha256,
        )

    def complete_halted(
        self,
        *,
        lease: Slice3TerminalAttemptLease,
        plan: Slice3Plan,
        activation_manifest_sha256: str,
        now: datetime,
        reason_code: str,
        phase: str,
        evidence: Slice3HaltedReconciliationEvidence,
        action_journal_sha256: str,
        read_journal_sha256: str,
    ) -> str:
        if not isinstance(evidence, Slice3HaltedReconciliationEvidence):
            raise Slice3TerminalArtifactError(
                "slice3_terminal_halted_evidence_invalid"
            )
        try:
            evidence.validate(plan=plan, now=now)
        except Exception:
            raise Slice3TerminalArtifactError(
                "slice3_terminal_halted_evidence_invalid"
            ) from None
        return self._complete(
            lease=lease,
            plan_sha256=plan.plan_sha256,
            activation_manifest_sha256=activation_manifest_sha256,
            now=now,
            status=Slice3OrchestrationStatus.HALTED,
            reason_code=reason_code,
            phase=phase,
            terminal_evidence=cast(
                Mapping[str, object],
                evidence.sanitized_evidence(plan=plan, now=now),
            ),
            action_journal_sha256=action_journal_sha256,
            read_journal_sha256=read_journal_sha256,
        )


class _Halt(RuntimeError):
    def __init__(self, reason_code: str, phase: str) -> None:
        self.reason_code = _require_reason(reason_code)
        self.phase = _require_reason(phase)
        super().__init__(reason_code)


@dataclass
class _ExecutionContext:
    phase: str = "claim_reservation"
    port: _Slice3Port | None = None
    mutation_started: bool = False
    final_reconciliation_attempted: bool = False
    final_reconciliation: _FinalReconciliation | None = None


@dataclass(frozen=True)
class _FinalReconciliation:
    position: Slice3PositionObservation | None
    open_orders: Slice3OpenOrderZeroProof | None
    margin: Slice3MarginSummary | None
    incomplete: bool


def _fresh(observed_at: datetime, *, now: datetime) -> bool:
    if observed_at.tzinfo is None or now.tzinfo is None:
        return False
    try:
        age = now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return False
    return age.total_seconds() >= 0 and age <= SLICE3_MAX_READ_AGE


def _nonnegative_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result


class Slice3TerminalRoundtripOrchestrator:
    """Execute exactly one sealed finite branch and prove the safe exit."""

    def __init__(
        self,
        *,
        action_store: FileSlice3ActionClaimStore,
        read_journal: FileSlice3ReadJournal,
        terminal_store: FileSlice3TerminalArtifactStore,
        port_factory: Callable[[Slice3ActivationSeal], _Slice3Port],
        now_provider: Callable[[], datetime],
        admission_store: _AdmissionStore | None = None,
    ) -> None:
        self.action_store = action_store
        self.read_journal = read_journal
        self.terminal_store = terminal_store
        self.port_factory = port_factory
        self.now_provider = now_provider
        self.admission_store = (
            production_slice3_admission_store()
            if admission_store is None
            else admission_store
        )
        self.gate = Slice3MutationGate(action_store)

    def _now(self) -> datetime:
        return _aware_utc(self.now_provider())

    @staticmethod
    def _path_bound(value: object, expected: Path) -> bool:
        if not isinstance(value, str) or not expected.is_absolute():
            return False
        return bool(
            value == str(expected)
            and os.path.isabs(value)
            and os.path.normpath(value) == value
        )

    def _read_activation(
        self,
        *,
        plan: Slice3Plan,
        activation_store: _ActivationStore,
        expected_manifest_sha256: str,
        now: datetime,
    ) -> Slice3ActivationSeal:
        try:
            _require_sha256(
                expected_manifest_sha256,
                "slice3_activation_binding_invalid",
            )
            plan.validate_risk_off_at(now)
            if plan.policy != SLICE3_LIVE_POLICY:
                raise ValueError
            seal = activation_store.read(
                now=now,
                expected_manifest_sha256=expected_manifest_sha256,
            )
            if (
                not isinstance(seal, Slice3ActivationSeal)
                or seal.manifest_sha256 != expected_manifest_sha256
            ):
                raise ValueError
            seal.manifest.validate_at(now)
            evidence = seal.manifest.sanitized_evidence()
            modules = evidence.get("module_sha256")
            schema_policy = evidence.get("schema_policy_sha256")
            if (
                not isinstance(modules, Mapping)
                or set(modules) != {"core", "port", "orchestrator"}
                or not isinstance(schema_policy, Mapping)
                or set(schema_policy)
                != {
                    "action_journal_schema",
                    "read_journal_schema",
                    "terminal_evidence_schema",
                    "slice3_live_policy",
                }
            ):
                raise ValueError
            runtime_modules = {
                "core": _runtime_file_sha256("futures_terminal_roundtrip.py"),
                "port": _runtime_file_sha256("futures_terminal_roundtrip_coinbase.py"),
                "orchestrator": _runtime_file_sha256(
                    "futures_terminal_roundtrip_orchestrator.py"
                ),
            }
            runtime_admission_module = _runtime_file_sha256(
                "futures_terminal_roundtrip_admission.py"
            )
            runtime_schema_policy = {
                "action_journal_schema": runtime_modules["core"],
                "read_journal_schema": _runtime_file_sha256(
                    "futures_terminal_roundtrip_reads.py"
                ),
                "terminal_evidence_schema": _runtime_file_sha256(
                    "futures_terminal_roundtrip_terminal.py"
                ),
                "slice3_live_policy": _canonical_sha256(
                    plan.policy.sanitized_evidence()
                ),
            }
            if (
                evidence.get("readiness") != "ready"
                or evidence.get("slice3_plan_sha256") != plan.plan_sha256
                or evidence.get("authorization_text_sha256")
                != plan.execution_authority.authorization_sha256
                or seal.manifest.authorization_text_sha256
                != plan.execution_authority.authorization_sha256
                or evidence.get("backend_revision") != plan.backend_revision
                or evidence.get("openapi_revision") != plan.openapi_revision
                or evidence.get("schema_versions") != _SCHEMA_VERSIONS
                or dict(modules) != runtime_modules
                or seal.manifest.core_module_sha256 != runtime_modules["core"]
                or seal.manifest.port_module_sha256 != runtime_modules["port"]
                or seal.manifest.orchestrator_module_sha256
                != runtime_modules["orchestrator"]
                or evidence.get("admission_module_sha256") != runtime_admission_module
                or seal.manifest.admission_module_sha256 != runtime_admission_module
                or evidence.get("admission_chain_sha256")
                != seal.manifest.admission_chain_sha256
                or evidence.get("admission_record_sha256")
                != seal.manifest.admission_record_sha256
                or evidence.get("admission_artifact_file_sha256")
                != seal.manifest.admission_artifact_file_sha256
                or dict(schema_policy) != runtime_schema_policy
                or seal.manifest.action_journal_schema_sha256
                != runtime_schema_policy["action_journal_schema"]
                or seal.manifest.read_journal_schema_sha256
                != runtime_schema_policy["read_journal_schema"]
                or seal.manifest.terminal_evidence_schema_sha256
                != runtime_schema_policy["terminal_evidence_schema"]
                or seal.manifest.slice3_live_policy_sha256
                != runtime_schema_policy["slice3_live_policy"]
                or evidence.get("attempt_limits") != _ATTEMPT_LIMITS
                or evidence.get("live_adapter_bound") is not True
                or evidence.get("route_registered") is not False
                or evidence.get("raw_identifier_values_included") is not False
                or self.admission_store.path != SLICE3_ADMISSION_ARTIFACT_PATH
                or not self._path_bound(
                    evidence.get("journal_path"), self.action_store.path
                )
                or not self._path_bound(
                    evidence.get("read_journal_path"), self.read_journal.path
                )
                or not self._path_bound(
                    evidence.get("terminal_evidence_path"),
                    self.terminal_store.path,
                )
            ):
                raise ValueError
            admission_seal = self.admission_store.read(
                now=now,
                expected_chain_sha256=(seal.manifest.admission_chain_sha256),
            )
            if not isinstance(admission_seal, Slice3AdmissionSeal):
                raise ValueError
            admission_seal.chain.validate_at(now)
            if (
                admission_seal.chain_sha256 != seal.manifest.admission_chain_sha256
                or admission_seal.chain.chain_sha256 != admission_seal.chain_sha256
                or admission_seal.record_sha256 != seal.manifest.admission_record_sha256
                or admission_seal.artifact_file_sha256
                != seal.manifest.admission_artifact_file_sha256
                or admission_seal.chain.plan_sha256 != plan.plan_sha256
                or admission_seal.chain.authorization_sha256
                != plan.execution_authority.authorization_sha256
            ):
                raise ValueError
            return seal
        except Exception:
            raise Slice3OrchestrationError(
                "slice3_activation_binding_invalid"
            ) from None

    def _read(
        self,
        *,
        plan: Slice3Plan,
        slot: Slice3ReadSlot,
        delegate: Callable[[datetime], Any],
        failure_reason: str,
        phase: str,
    ) -> Any:
        observed_at = self._now()
        try:
            return self.read_journal.execute(
                plan_sha256=plan.plan_sha256,
                slot=slot,
                declaration=slice3_read_declaration(slot),
                delegate=lambda: delegate(observed_at),
            )
        except Exception:
            raise _Halt(failure_reason, phase) from None

    @staticmethod
    def _validate_zero_orders(
        proof: object,
        *,
        now: datetime,
    ) -> Slice3OpenOrderZeroProof:
        if not isinstance(proof, Slice3OpenOrderZeroProof) or not (
            proof.authoritative is True
            and proof.pagination_complete is True
            and proof.scope == "exact_product_active_transitional_orders"
            and proof.product_id == SLICE3_PRODUCT_ID
            and proof.exact_product_active_order_count == 0
            and _SHA256.fullmatch(proof.snapshot_sha256) is not None
            and proof.raw_response_included is False
            and proof.identifier_values_included is False
            and _fresh(proof.observed_at, now=now)
        ):
            raise _Halt(
                "pre_create_open_orders_invalid",
                "pre_create_open_orders",
            )
        return proof

    @staticmethod
    def _validate_pre_create_margin(
        margin: object,
        *,
        plan: Slice3Plan,
        now: datetime,
    ) -> Slice3MarginSummary:
        if not isinstance(margin, Slice3MarginSummary):
            raise _Halt("pre_create_margin_invalid", "pre_create_margin")
        values = (
            _nonnegative_decimal(margin.available_margin_usdc),
            _nonnegative_decimal(margin.total_usd_balance_usdc),
            _nonnegative_decimal(margin.initial_margin_usdc),
            _nonnegative_decimal(margin.liquidation_threshold_usdc),
        )
        required = Decimal(plan.preview.order_margin_total) + Decimal(
            plan.preview.commission_total
        )
        if not (
            margin.status == "ready"
            and margin.account_family == "coinbase_futures_us_cfm"
            and margin.retail_regular_margin_window
            == plan.margin_windows.retail_regular
            and margin.retail_intraday_margin_window
            == plan.margin_windows.retail_intraday_margin_1
            and margin.intraday_margin_setting
            == plan.margin_windows.intraday_margin_setting
            and margin.intraday_margin_killswitch_enabled
            is plan.margin_windows.intraday_margin_killswitch_enabled
            and margin.intraday_margin_enrollment_killswitch_enabled
            is plan.margin_windows.intraday_margin_enrollment_killswitch_enabled
            and _SHA256.fullmatch(margin.snapshot_sha256) is not None
            and margin.raw_response_included is False
            and margin.identifier_values_included is False
            and _fresh(margin.observed_at, now=now)
            and all(value is not None for value in values)
            and cast(Decimal, values[0]) > required
        ):
            raise _Halt("pre_create_margin_invalid", "pre_create_margin")
        return margin

    @staticmethod
    def _validate_opening_evidence(
        evidence: object,
        *,
        plan: Slice3Plan,
        source: Slice3OrderResolutionSource,
        unknown_create: bool,
    ) -> Slice3ExactOrderEvidence:
        if not isinstance(evidence, Slice3ExactOrderEvidence):
            raise _Halt(
                "opening_order_evidence_invalid",
                "post_create_order",
            )
        observation = evidence.observation
        if unknown_create and not (
            observation.resolution_source
            is Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
            and observation.exact_client_order_match_count == 1
        ):
            raise _Halt(
                "unknown_create_not_uniquely_resolved",
                "post_create_order",
            )
        if not (
            observation.resolution_source is source
            and evidence.side is OrderSide.BUY
            and evidence.side_exact is True
            and evidence.configuration_exact is True
            and evidence.order_configuration_sha256
            == Slice3TerminalRoundtripEvidence.opening_configuration_sha256(plan)
            and evidence.raw_response_included is False
            and evidence.identifier_values_included is False
        ):
            raise _Halt(
                "opening_order_evidence_invalid",
                "post_create_order",
            )
        return evidence

    @staticmethod
    def _decision(
        *,
        plan: Slice3Plan,
        opening: Slice3ExactOrderEvidence,
        position: Slice3PositionObservation,
        create_outcome: Slice3MutationOutcome,
        now: datetime,
    ) -> Slice3Directive:
        directive = decide_slice3_next_action(
            plan,
            order=opening.observation,
            position=position,
            now=now,
            create_outcome=create_outcome,
        )
        if directive.kind in {
            Slice3DirectiveKind.READ_ONLY_RECONCILE,
            Slice3DirectiveKind.HALT_SAFETY,
        }:
            raise _Halt(directive.reason_code, "branch_decision")
        return directive

    def _retire(
        self,
        *,
        plan: Slice3Plan,
        action: Slice3ActionKind,
        reason_code: str,
        dependency: object,
    ) -> None:
        self.action_store.retire_unused(
            plan.action_claim(action),
            reason_code=reason_code,
            dependency_evidence_sha256=_canonical_sha256(dependency),
        )

    def _retire_if_claimed(
        self,
        *,
        plan: Slice3Plan,
        action: Slice3ActionKind,
        reason_code: str,
        dependency: object,
        phase: str,
    ) -> None:
        """Retire an unused recovery claim once, or accept its prior retirement."""

        record = self.action_store.inspect(plan.action_claim(action))
        if record is not None and record.event is Slice3ClaimEvent.CLAIM:
            self._retire(
                plan=plan,
                action=action,
                reason_code=reason_code,
                dependency=dependency,
            )
            return
        if record is not None and record.event is Slice3ClaimEvent.RETIRED:
            return
        raise _Halt(f"recovery_{action.value}_state_invalid", phase)

    def _action_binding(
        self,
        *,
        plan: Slice3Plan,
        action: Slice3ActionKind,
    ) -> Slice3ActionTerminalBinding:
        record = self.action_store.inspect(plan.action_claim(action))
        if (
            record is None
            or record.event
            not in {
                Slice3ClaimEvent.OUTCOME,
                Slice3ClaimEvent.RETIRED,
            }
            or record.reason_code is None
        ):
            raise _Halt("action_terminal_binding_missing", "terminal_evidence")
        return Slice3ActionTerminalBinding(
            action=action,
            terminal_event=cast(Any, record.event.value),
            record_sha256=record.record_sha256,
            outcome=(None if record.outcome is None else record.outcome.value),
            reason_code=record.reason_code,
        )

    def _final_reconciliation(
        self,
        *,
        context: _ExecutionContext,
        plan: Slice3Plan,
        recovery: bool = False,
    ) -> _FinalReconciliation:
        context.final_reconciliation_attempted = True
        port = context.port
        if port is None:
            reconciliation = _FinalReconciliation(None, None, None, True)
            context.final_reconciliation = reconciliation
            return reconciliation
        incomplete = False
        final_position: Slice3PositionObservation | None = None
        final_open_orders: Slice3OpenOrderZeroProof | None = None
        final_margin: Slice3MarginSummary | None = None
        position_slot = (
            Slice3ReadSlot.RECOVERY_FINAL_POSITION
            if recovery
            else Slice3ReadSlot.FINAL_POSITION
        )
        open_orders_slot = (
            Slice3ReadSlot.RECOVERY_FINAL_OPEN_ORDERS
            if recovery
            else Slice3ReadSlot.FINAL_OPEN_ORDERS
        )
        margin_slot = (
            Slice3ReadSlot.RECOVERY_FINAL_MARGIN
            if recovery
            else Slice3ReadSlot.FINAL_MARGIN
        )
        try:
            value = self.read_journal.execute(
                plan_sha256=plan.plan_sha256,
                slot=position_slot,
                declaration=slice3_read_declaration(position_slot),
                delegate=lambda: port.read_position(observed_at=self._now()),
            )
            if not isinstance(value, Slice3PositionObservation):
                incomplete = True
            else:
                final_position = value
        except Exception:
            incomplete = True
        try:
            value = self.read_journal.execute(
                plan_sha256=plan.plan_sha256,
                slot=open_orders_slot,
                declaration=slice3_read_declaration(open_orders_slot),
                delegate=lambda: port.prove_zero_open_orders(observed_at=self._now()),
            )
            if not isinstance(value, Slice3OpenOrderZeroProof):
                incomplete = True
            else:
                final_open_orders = value
        except Exception:
            incomplete = True
        try:
            value = self.read_journal.execute(
                plan_sha256=plan.plan_sha256,
                slot=margin_slot,
                declaration=slice3_read_declaration(margin_slot),
                delegate=lambda: port.read_margin_summary(observed_at=self._now()),
            )
            if not isinstance(value, Slice3MarginSummary):
                incomplete = True
            else:
                final_margin = value
        except Exception:
            incomplete = True
        reconciliation = _FinalReconciliation(
            final_position,
            final_open_orders,
            final_margin,
            incomplete,
        )
        context.final_reconciliation = reconciliation
        return reconciliation

    def _close(
        self,
        *,
        context: _ExecutionContext,
        plan: Slice3Plan,
        opening: Slice3ExactOrderEvidence,
        create_outcome: Slice3MutationOutcome,
        cancel_was_called: bool,
        position: Slice3PositionObservation | None = None,
        recovery: bool = False,
    ) -> Slice3ExactOrderEvidence:
        port = cast(_Slice3Port, context.port)
        if position is None:
            context.phase = "pre_close_position"
            position = self._read(
                plan=plan,
                slot=Slice3ReadSlot.PRE_CLOSE_POSITION,
                delegate=lambda observed_at: port.read_position(
                    observed_at=observed_at
                ),
                failure_reason="pre_close_position_read_failed",
                phase="pre_close_position",
            )
        if not isinstance(position, Slice3PositionObservation):
            raise _Halt("pre_close_position_invalid", "pre_close_position")
        directive = self._decision(
            plan=plan,
            opening=opening,
            position=position,
            create_outcome=create_outcome,
            now=self._now(),
        )
        if directive.kind is not Slice3DirectiveKind.CLOSE_EXACT_DELTA:
            raise _Halt("close_directive_missing", "pre_close_position")
        context.phase = "pre_close_market"
        market = self._read(
            plan=plan,
            slot=(
                Slice3ReadSlot.RECOVERY_MARKET
                if recovery
                else Slice3ReadSlot.PRE_CLOSE_MARKET
            ),
            delegate=lambda observed_at: port.read_market_reference(
                observed_at=observed_at
            ),
            failure_reason="pre_close_market_read_failed",
            phase="pre_close_market",
        )
        if not isinstance(market, Slice3MarketReference):
            raise _Halt("pre_close_market_invalid", "pre_close_market")
        context.phase = "pre_close_open_orders"
        open_orders = self._read(
            plan=plan,
            slot=(
                Slice3ReadSlot.RECOVERY_PRE_CLOSE_OPEN_ORDERS
                if recovery
                else Slice3ReadSlot.PRE_CLOSE_OPEN_ORDERS
            ),
            delegate=lambda observed_at: port.prove_zero_open_orders(
                observed_at=observed_at
            ),
            failure_reason="pre_close_open_orders_read_failed",
            phase="pre_close_open_orders",
        )
        if not isinstance(open_orders, Slice3OpenOrderZeroProof):
            raise _Halt(
                "pre_close_open_orders_invalid",
                "pre_close_open_orders",
            )
        context.phase = "close_execution"
        result = self.gate.execute_close(
            plan,
            order=opening.observation,
            position=position,
            market=market,
            open_orders=open_orders,
            port_factory=lambda: port,
            now=self._now(),
        )
        if not cancel_was_called:
            retirement_reason = (
                "cancel_not_required_filled_branch"
                if opening.observation.status is OrderStatus.FILLED
                else "cancel_not_required_terminal_branch"
            )
            self._retire(
                plan=plan,
                action=Slice3ActionKind.CANCEL,
                reason_code=retirement_reason,
                dependency={
                    "schema_version": "slice3-cancel-retirement-v1",
                    "plan_sha256": plan.plan_sha256,
                    "opening_order": opening.sanitized_evidence(),
                    "close_outcome": result.sanitized_evidence(),
                },
            )
        if result.outcome is Slice3MutationOutcome.REJECTED:
            raise _Halt("close_explicitly_rejected", "close_execution")
        context.phase = "post_close_order"
        if result.outcome is Slice3MutationOutcome.UNKNOWN:
            close = self._read(
                plan=plan,
                slot=(
                    Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID
                    if recovery
                    else Slice3ReadSlot.POST_CLOSE_ORDER
                ),
                delegate=lambda observed_at: (
                    port.resolve_exact_close_order_by_client_order_id(
                        client_order_id=plan.close_client_order_id,
                        observed_at=observed_at,
                        expected_close_size=directive.close_contracts,
                    )
                ),
                failure_reason="post_close_order_read_failed",
                phase="post_close_order",
            )
            if not isinstance(close, Slice3ExactOrderEvidence) or not (
                close.observation.resolution_source
                is Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
                and close.observation.exact_client_order_match_count == 1
            ):
                raise _Halt(
                    "unknown_close_not_uniquely_resolved",
                    "post_close_order",
                )
        else:
            if result.exchange_order_id is None:
                raise _Halt(
                    "close_accepted_exchange_identity_missing",
                    "post_close_order",
                )
            close = self._read(
                plan=plan,
                slot=(
                    Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID
                    if recovery
                    else Slice3ReadSlot.POST_CLOSE_ORDER
                ),
                delegate=lambda observed_at: port.read_exact_order(
                    client_order_id=plan.close_client_order_id,
                    exchange_order_id=result.exchange_order_id,
                    observed_at=observed_at,
                    expected_close_size=directive.close_contracts,
                ),
                failure_reason="post_close_order_read_failed",
                phase="post_close_order",
            )
            if not isinstance(close, Slice3ExactOrderEvidence):
                raise _Halt("close_order_evidence_invalid", "post_close_order")
        return cast(Slice3ExactOrderEvidence, close)

    def _execute(
        self,
        *,
        context: _ExecutionContext,
        plan: Slice3Plan,
        seal: Slice3ActivationSeal,
    ) -> Slice3TerminalRoundtripEvidence:
        context.phase = "claim_reservation"
        self.gate.reserve_action_claims(plan, now=self._now())
        context.phase = "port_construction"
        try:
            context.port = self.port_factory(seal)
        except Exception:
            raise _Halt("port_construction_failed", "port_construction") from None
        port = context.port
        if port is None:
            raise _Halt("port_construction_failed", "port_construction")

        context.phase = "pre_create_open_orders"
        open_orders = self._read(
            plan=plan,
            slot=Slice3ReadSlot.PRE_CREATE_OPEN_ORDERS,
            delegate=lambda observed_at: port.prove_zero_open_orders(
                observed_at=observed_at
            ),
            failure_reason="pre_create_open_orders_read_failed",
            phase="pre_create_open_orders",
        )
        zero_orders = self._validate_zero_orders(open_orders, now=self._now())
        context.phase = "pre_create_position"
        pre_position = self._read(
            plan=plan,
            slot=Slice3ReadSlot.PRE_CREATE_POSITION,
            delegate=lambda observed_at: port.read_position(observed_at=observed_at),
            failure_reason="pre_create_position_read_failed",
            phase="pre_create_position",
        )
        if not isinstance(pre_position, Slice3PositionObservation):
            raise _Halt("pre_create_position_invalid", "pre_create_position")
        context.phase = "pre_create_margin"
        pre_margin = self._read(
            plan=plan,
            slot=Slice3ReadSlot.PRE_CREATE_MARGIN,
            delegate=lambda observed_at: port.read_margin_summary(
                observed_at=observed_at
            ),
            failure_reason="pre_create_margin_read_failed",
            phase="pre_create_margin",
        )
        self._validate_pre_create_margin(
            pre_margin,
            plan=plan,
            now=self._now(),
        )
        try:
            pre_position.validate(plan, now=self._now())
        except Exception:
            raise _Halt(
                "pre_create_position_invalid",
                "pre_create_position",
            ) from None
        pre_create = Slice3PreCreateEvidence(
            open_orders_authoritative=zero_orders.authoritative,
            open_orders_pagination_complete=zero_orders.pagination_complete,
            open_orders_scope=zero_orders.scope,
            exact_product_active_order_count=(
                zero_orders.exact_product_active_order_count
            ),
            open_orders_snapshot_sha256=zero_orders.snapshot_sha256,
            open_orders_observed_at=zero_orders.observed_at,
            position=pre_position,
            margin_authoritative=True,
            margin_status=pre_margin.status,
            margin_account_family=pre_margin.account_family,
            margin_available_usdc=pre_margin.available_margin_usdc,
            margin_windows=plan.margin_windows,
            margin_observed_at=pre_margin.observed_at,
            margin_snapshot_sha256=pre_margin.snapshot_sha256,
        )

        context.phase = "create_execution"
        context.mutation_started = True
        create_result = self.gate.execute_create(
            plan,
            pre_create=pre_create,
            port_factory=lambda: port,
            now=self._now(),
        )
        opening: Slice3ExactOrderEvidence | None = None
        close: Slice3ExactOrderEvidence | None = None
        if create_result.outcome is Slice3MutationOutcome.REJECTED:
            create_record = self.action_store.inspect(
                plan.action_claim(Slice3ActionKind.CREATE)
            )
            dependency = {
                "schema_version": "slice3-create-rejection-retirement-v1",
                "plan_sha256": plan.plan_sha256,
                "create_record_sha256": (
                    None if create_record is None else create_record.record_sha256
                ),
            }
            self._retire(
                plan=plan,
                action=Slice3ActionKind.CANCEL,
                reason_code="cancel_not_required_create_rejected",
                dependency=dependency,
            )
            self._retire(
                plan=plan,
                action=Slice3ActionKind.CLOSE,
                reason_code="close_not_required_create_rejected",
                dependency=dependency,
            )
        else:
            context.phase = "post_create_order"
            if create_result.outcome is Slice3MutationOutcome.UNKNOWN:
                value = self._read(
                    plan=plan,
                    slot=Slice3ReadSlot.POST_CREATE_ORDER,
                    delegate=lambda observed_at: (
                        port.resolve_exact_order_by_client_order_id(
                            client_order_id=plan.create.client_order_id,
                            observed_at=observed_at,
                        )
                    ),
                    failure_reason="post_create_order_read_failed",
                    phase="post_create_order",
                )
                opening = self._validate_opening_evidence(
                    value,
                    plan=plan,
                    source=(Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP),
                    unknown_create=True,
                )
            else:
                if create_result.exchange_order_id is None:
                    raise _Halt(
                        "create_accepted_exchange_identity_missing",
                        "post_create_order",
                    )
                value = self._read(
                    plan=plan,
                    slot=Slice3ReadSlot.POST_CREATE_ORDER,
                    delegate=lambda observed_at: port.read_exact_order(
                        client_order_id=plan.create.client_order_id,
                        exchange_order_id=create_result.exchange_order_id,
                        observed_at=observed_at,
                    ),
                    failure_reason="post_create_order_read_failed",
                    phase="post_create_order",
                )
                opening = self._validate_opening_evidence(
                    value,
                    plan=plan,
                    source=Slice3OrderResolutionSource.AUTHORITATIVE_ORDER_READ,
                    unknown_create=False,
                )
            context.phase = "post_create_position"
            post_position = self._read(
                plan=plan,
                slot=Slice3ReadSlot.POST_CREATE_POSITION,
                delegate=lambda observed_at: port.read_position(
                    observed_at=observed_at
                ),
                failure_reason="post_create_position_read_failed",
                phase="post_create_position",
            )
            if not isinstance(post_position, Slice3PositionObservation):
                raise _Halt(
                    "post_create_position_invalid",
                    "post_create_position",
                )
            directive = self._decision(
                plan=plan,
                opening=opening,
                position=post_position,
                create_outcome=create_result.outcome,
                now=self._now(),
            )
            if directive.kind in {
                Slice3DirectiveKind.CANCEL_OPEN,
                Slice3DirectiveKind.CANCEL_RESIDUAL,
            }:
                context.phase = "cancel_execution"
                self.gate.execute_cancel(
                    plan,
                    order=opening.observation,
                    position=post_position,
                    port_factory=lambda: port,
                    now=self._now(),
                )
                exchange_order_id = opening.observation.exchange_order_id
                if exchange_order_id is None:
                    raise _Halt(
                        "cancelled_order_exchange_identity_missing",
                        "post_cancel_order",
                    )
                context.phase = "post_cancel_order"
                value = self._read(
                    plan=plan,
                    slot=Slice3ReadSlot.POST_CANCEL_TERMINAL_ORDER,
                    delegate=lambda observed_at: port.read_exact_order(
                        client_order_id=plan.create.client_order_id,
                        exchange_order_id=exchange_order_id,
                        observed_at=observed_at,
                    ),
                    failure_reason="post_cancel_order_read_failed",
                    phase="post_cancel_order",
                )
                opening = self._validate_opening_evidence(
                    value,
                    plan=plan,
                    source=Slice3OrderResolutionSource.AUTHORITATIVE_ORDER_READ,
                    unknown_create=False,
                )
                context.phase = "pre_close_position"
                post_cancel_position = self._read(
                    plan=plan,
                    slot=Slice3ReadSlot.PRE_CLOSE_POSITION,
                    delegate=lambda observed_at: port.read_position(
                        observed_at=observed_at
                    ),
                    failure_reason="pre_close_position_read_failed",
                    phase="pre_close_position",
                )
                if not isinstance(post_cancel_position, Slice3PositionObservation):
                    raise _Halt(
                        "pre_close_position_invalid",
                        "pre_close_position",
                    )
                directive = self._decision(
                    plan=plan,
                    opening=opening,
                    position=post_cancel_position,
                    create_outcome=create_result.outcome,
                    now=self._now(),
                )
                if directive.kind is Slice3DirectiveKind.CLOSE_EXACT_DELTA:
                    context.phase = "pre_close_market"
                    market = self._read(
                        plan=plan,
                        slot=Slice3ReadSlot.PRE_CLOSE_MARKET,
                        delegate=lambda observed_at: port.read_market_reference(
                            observed_at=observed_at
                        ),
                        failure_reason="pre_close_market_read_failed",
                        phase="pre_close_market",
                    )
                    if not isinstance(market, Slice3MarketReference):
                        raise _Halt(
                            "pre_close_market_invalid",
                            "pre_close_market",
                        )
                    context.phase = "pre_close_open_orders"
                    open_orders = self._read(
                        plan=plan,
                        slot=Slice3ReadSlot.PRE_CLOSE_OPEN_ORDERS,
                        delegate=lambda observed_at: port.prove_zero_open_orders(
                            observed_at=observed_at
                        ),
                        failure_reason="pre_close_open_orders_read_failed",
                        phase="pre_close_open_orders",
                    )
                    if not isinstance(open_orders, Slice3OpenOrderZeroProof):
                        raise _Halt(
                            "pre_close_open_orders_invalid",
                            "pre_close_open_orders",
                        )
                    context.phase = "close_execution"
                    close_result = self.gate.execute_close(
                        plan,
                        order=opening.observation,
                        position=post_cancel_position,
                        market=market,
                        open_orders=open_orders,
                        port_factory=lambda: port,
                        now=self._now(),
                    )
                    close = self._read_close_result(
                        context=context,
                        plan=plan,
                        port=port,
                        directive=directive,
                        result=close_result,
                    )
                elif directive.kind in {
                    Slice3DirectiveKind.COMPLETE_FLAT,
                    Slice3DirectiveKind.COMPLETE_REJECTED,
                }:
                    self._retire(
                        plan=plan,
                        action=Slice3ActionKind.CLOSE,
                        reason_code="close_not_required_zero_exposure",
                        dependency={
                            "schema_version": "slice3-zero-close-retirement-v1",
                            "plan_sha256": plan.plan_sha256,
                            "opening_order": opening.sanitized_evidence(),
                        },
                    )
                else:
                    raise _Halt(
                        "post_cancel_order_not_terminal",
                        "post_cancel_order",
                    )
            elif directive.kind is Slice3DirectiveKind.CLOSE_EXACT_DELTA:
                close = self._close(
                    context=context,
                    plan=plan,
                    opening=opening,
                    create_outcome=create_result.outcome,
                    cancel_was_called=False,
                )
            elif directive.kind in {
                Slice3DirectiveKind.COMPLETE_FLAT,
                Slice3DirectiveKind.COMPLETE_REJECTED,
            }:
                self._retire(
                    plan=plan,
                    action=Slice3ActionKind.CANCEL,
                    reason_code="cancel_not_required_terminal_branch",
                    dependency={
                        "schema_version": "slice3-terminal-cancel-retirement-v1",
                        "plan_sha256": plan.plan_sha256,
                        "opening_order": opening.sanitized_evidence(),
                    },
                )
                self._retire(
                    plan=plan,
                    action=Slice3ActionKind.CLOSE,
                    reason_code="close_not_required_zero_exposure",
                    dependency={
                        "schema_version": "slice3-zero-close-retirement-v1",
                        "plan_sha256": plan.plan_sha256,
                        "opening_order": opening.sanitized_evidence(),
                    },
                )
            else:
                raise _Halt("branch_not_terminal", "branch_decision")

        context.phase = "final_reconciliation"
        final = self._final_reconciliation(
            context=context,
            plan=plan,
        )
        if (
            final.incomplete
            or final.position is None
            or final.open_orders is None
            or final.margin is None
        ):
            raise _Halt(
                "final_reconciliation_incomplete",
                "final_reconciliation",
            )
        context.phase = "terminal_evidence"
        read_hash = self._required_journal_sha256(self.read_journal)
        self._required_journal_sha256(self.action_store)
        try:
            return Slice3TerminalRoundtripEvidence.build(
                plan=plan,
                opening_order=opening,
                close_order=close,
                final_position=final.position,
                final_open_orders=final.open_orders,
                final_margin=final.margin,
                create_action=self._action_binding(
                    plan=plan, action=Slice3ActionKind.CREATE
                ),
                cancel_action=self._action_binding(
                    plan=plan, action=Slice3ActionKind.CANCEL
                ),
                close_action=self._action_binding(
                    plan=plan, action=Slice3ActionKind.CLOSE
                ),
                read_journal_sha256=read_hash,
                completed_at=self._now(),
            )
        except _Halt:
            raise
        except Exception:
            raise _Halt(
                "terminal_evidence_invalid",
                "terminal_evidence",
            ) from None

    def _read_close_result(
        self,
        *,
        context: _ExecutionContext,
        plan: Slice3Plan,
        port: _Slice3Port,
        directive: Slice3Directive,
        result: Slice3MutationResult,
        recovery: bool = False,
    ) -> Slice3ExactOrderEvidence:
        if result.outcome is Slice3MutationOutcome.REJECTED:
            raise _Halt("close_explicitly_rejected", "close_execution")
        context.phase = "post_close_order"
        if result.outcome is Slice3MutationOutcome.UNKNOWN:
            close = self._read(
                plan=plan,
                slot=(
                    Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID
                    if recovery
                    else Slice3ReadSlot.POST_CLOSE_ORDER
                ),
                delegate=lambda observed_at: (
                    port.resolve_exact_close_order_by_client_order_id(
                        client_order_id=plan.close_client_order_id,
                        observed_at=observed_at,
                        expected_close_size=directive.close_contracts,
                    )
                ),
                failure_reason="post_close_order_read_failed",
                phase="post_close_order",
            )
            if not isinstance(close, Slice3ExactOrderEvidence) or not (
                close.observation.resolution_source
                is Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
                and close.observation.exact_client_order_match_count == 1
            ):
                raise _Halt(
                    "unknown_close_not_uniquely_resolved",
                    "post_close_order",
                )
            return close
        if result.exchange_order_id is None:
            raise _Halt(
                "close_accepted_exchange_identity_missing",
                "post_close_order",
            )
        close = self._read(
            plan=plan,
            slot=(
                Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID
                if recovery
                else Slice3ReadSlot.POST_CLOSE_ORDER
            ),
            delegate=lambda observed_at: port.read_exact_order(
                client_order_id=plan.close_client_order_id,
                exchange_order_id=result.exchange_order_id,
                observed_at=observed_at,
                expected_close_size=directive.close_contracts,
            ),
            failure_reason="post_close_order_read_failed",
            phase="post_close_order",
        )
        if not isinstance(close, Slice3ExactOrderEvidence):
            raise _Halt("close_order_evidence_invalid", "post_close_order")
        return close

    @staticmethod
    def _required_journal_sha256(store: object) -> str:
        try:
            reader = getattr(store, "read_all")
            path = Path(getattr(store, "path"))
            reader()
            descriptor = os.open(path, os.O_RDONLY | _NOFOLLOW | _CLOEXEC)
            try:
                opened = os.fstat(descriptor)
                linked = os.lstat(path)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) != 0o600
                    or opened.st_nlink != 1
                    or opened.st_dev != linked.st_dev
                    or opened.st_ino != linked.st_ino
                ):
                    raise OSError
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(descriptor, 64 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(descriptor)
                if (
                    opened.st_size != after.st_size
                    or opened.st_mtime_ns != after.st_mtime_ns
                    or opened.st_ino != after.st_ino
                ):
                    raise OSError
            finally:
                os.close(descriptor)
            reader()
            if not chunks:
                raise OSError
            return hashlib.sha256(b"".join(chunks)).hexdigest()
        except Exception:
            raise Slice3OrchestrationError("slice3_journal_hash_unavailable") from None

    @classmethod
    def _safe_journal_sha256(cls, store: object) -> str:
        try:
            return cls._required_journal_sha256(store)
        except Slice3OrchestrationError:
            return _EMPTY_SHA256

    def _halted_reconciliation_evidence(
        self,
        *,
        context: _ExecutionContext,
        plan: Slice3Plan,
    ) -> Slice3HaltedReconciliationEvidence:
        final = context.final_reconciliation
        return Slice3HaltedReconciliationEvidence.build(
            plan=plan,
            mutation_began=context.mutation_started,
            final_reconciliation_attempted=(
                context.final_reconciliation_attempted
            ),
            position=None if final is None else final.position,
            open_orders=None if final is None else final.open_orders,
            margin=None if final is None else final.margin,
            completed_at=self._now(),
        )

    def _retire_halt_claims(self, *, plan: Slice3Plan, reason_code: str) -> None:
        dependency = _canonical_sha256(
            {
                "schema_version": "slice3-safety-halt-retirement-v1",
                "plan_sha256": plan.plan_sha256,
                "halt_reason_code": reason_code,
            }
        )
        for action in (
            Slice3ActionKind.CREATE,
            Slice3ActionKind.CANCEL,
            Slice3ActionKind.CLOSE,
        ):
            try:
                claim = plan.action_claim(action)
                record = self.action_store.inspect(claim)
                if record is None:
                    continue
                if record.event is Slice3ClaimEvent.CLAIM:
                    self.action_store.retire_unused(
                        claim,
                        reason_code=f"{action.value}_not_executed_safety_halt",
                        dependency_evidence_sha256=dependency,
                    )
                elif record.event is Slice3ClaimEvent.EVIDENCE_BOUND:
                    self.action_store.reject_before_boundary(
                        claim,
                        reason_code=f"{action.value}_blocked_before_boundary",
                    )
            except Exception:
                continue

    def _terminalize_recovery_boundaries(self, *, plan: Slice3Plan) -> None:
        """Consume crash-left action/read boundaries without replaying them."""

        for action in (
            Slice3ActionKind.CREATE,
            Slice3ActionKind.CANCEL,
            Slice3ActionKind.CLOSE,
        ):
            try:
                claim = plan.action_claim(action)
                record = self.action_store.inspect(claim)
                if (
                    record is not None
                    and record.event is Slice3ClaimEvent.EXCHANGE_BOUNDARY
                ):
                    self.action_store.recover_boundary_as_unknown(claim)
            except Exception:
                continue
        for slot in Slice3ReadSlot:
            try:
                record = self.read_journal.inspect(
                    plan_sha256=plan.plan_sha256,
                    slot=slot,
                )
                if (
                    record is not None
                    and record.event is Slice3ReadRecordEvent.BOUNDARY_RESERVED
                    and record.outcome is Slice3ReadOutcome.RESERVED
                ):
                    self.read_journal.recover_reserved_as_failed(
                        plan_sha256=plan.plan_sha256,
                        slot=slot,
                        declaration=slice3_read_declaration(slot),
                    )
            except Exception:
                continue

    def _recover_interrupted_attempt(
        self,
        *,
        lease: Slice3TerminalAttemptLease,
        plan: Slice3Plan,
        seal: Slice3ActivationSeal,
    ) -> Slice3OrchestrationResult:
        """Terminalize pre-Create state or run the finite post-Create risk-off."""

        reason_code = "interrupted_attempt_recovered"
        create_before = self.action_store.inspect(
            plan.action_claim(Slice3ActionKind.CREATE)
        )
        create_crossed_boundary = bool(
            create_before is not None
            and create_before.event
            in {
                Slice3ClaimEvent.EXCHANGE_BOUNDARY,
                Slice3ClaimEvent.OUTCOME,
            }
        )
        context = _ExecutionContext(
            phase=(
                "interrupted_risk_off"
                if create_crossed_boundary
                else "interrupted_recovery"
            ),
            mutation_started=create_crossed_boundary,
        )
        for action in (
            Slice3ActionKind.CREATE,
            Slice3ActionKind.CANCEL,
            Slice3ActionKind.CLOSE,
        ):
            try:
                claim = plan.action_claim(action)
                record = self.action_store.inspect(claim)
                if (
                    record is not None
                    and record.event is Slice3ClaimEvent.EXCHANGE_BOUNDARY
                ):
                    self.action_store.recover_boundary_as_unknown(claim)
            except Exception:
                continue
        for slot in Slice3ReadSlot:
            try:
                record = self.read_journal.inspect(
                    plan_sha256=plan.plan_sha256,
                    slot=slot,
                )
                if (
                    record is not None
                    and record.event is Slice3ReadRecordEvent.BOUNDARY_RESERVED
                    and record.outcome is Slice3ReadOutcome.RESERVED
                ):
                    self.read_journal.recover_reserved_as_failed(
                        plan_sha256=plan.plan_sha256,
                        slot=slot,
                        declaration=slice3_read_declaration(slot),
                    )
            except Exception:
                continue
        if create_crossed_boundary:
            try:
                evidence = self._execute_recovered_create_risk_off(
                    context=context,
                    plan=plan,
                    seal=seal,
                )
                read_hash = self._required_journal_sha256(self.read_journal)
                action_hash = self._required_journal_sha256(self.action_store)
            except _Halt as exc:
                reason_code = exc.reason_code
                phase = exc.phase
            except Exception:
                reason_code = "interrupted_risk_off_failed"
                phase = "interrupted_risk_off"
            else:
                artifact_hash = self.terminal_store.complete_restored(
                    lease=lease,
                    plan_sha256=plan.plan_sha256,
                    activation_manifest_sha256=seal.manifest_sha256,
                    now=self._now(),
                    evidence=evidence,
                    action_journal_sha256=action_hash,
                    read_journal_sha256=read_hash,
                )
                return Slice3OrchestrationResult(
                    status=Slice3OrchestrationStatus.RESTORED_BASELINE,
                    terminal_evidence=evidence,
                    reason_code="restored_baseline",
                    terminal_artifact_sha256=artifact_hash,
                )
            if not context.final_reconciliation_attempted and context.port is not None:
                self._final_reconciliation(
                    context=context,
                    plan=plan,
                    recovery=True,
                )
            self._retire_halt_claims(plan=plan, reason_code=reason_code)
            read_hash = self._safe_journal_sha256(self.read_journal)
            action_hash = self._safe_journal_sha256(self.action_store)
            halted_evidence = self._halted_reconciliation_evidence(
                context=context,
                plan=plan,
            )
            artifact_hash = self.terminal_store.complete_halted(
                lease=lease,
                plan=plan,
                activation_manifest_sha256=seal.manifest_sha256,
                now=self._now(),
                reason_code=reason_code,
                phase=phase,
                evidence=halted_evidence,
                action_journal_sha256=action_hash,
                read_journal_sha256=read_hash,
            )
            return Slice3OrchestrationResult(
                status=Slice3OrchestrationStatus.HALTED,
                terminal_evidence=halted_evidence,
                reason_code=reason_code,
                terminal_artifact_sha256=artifact_hash,
            )
        self._retire_halt_claims(plan=plan, reason_code=reason_code)
        read_hash = self._safe_journal_sha256(self.read_journal)
        action_hash = self._safe_journal_sha256(self.action_store)
        halted_evidence = self._halted_reconciliation_evidence(
            context=context,
            plan=plan,
        )
        artifact_hash = self.terminal_store.complete_halted(
            lease=lease,
            plan=plan,
            activation_manifest_sha256=seal.manifest_sha256,
            now=self._now(),
            reason_code=reason_code,
            phase="interrupted_recovery",
            evidence=halted_evidence,
            action_journal_sha256=action_hash,
            read_journal_sha256=read_hash,
        )
        return Slice3OrchestrationResult(
            status=Slice3OrchestrationStatus.HALTED,
            terminal_evidence=halted_evidence,
            reason_code=reason_code,
            terminal_artifact_sha256=artifact_hash,
        )

    def _execute_recovered_create_risk_off(
        self,
        *,
        context: _ExecutionContext,
        plan: Slice3Plan,
        seal: Slice3ActivationSeal,
    ) -> Slice3TerminalRoundtripEvidence:
        """Resolve an interrupted Create once, then run only risk-off actions."""

        plan.validate_risk_off_at(self._now())
        if context.port is None:
            try:
                context.port = self.port_factory(seal)
            except Exception:
                raise _Halt(
                    "interrupted_risk_off_port_failed",
                    "interrupted_risk_off",
                ) from None
        port = context.port
        if port is None:
            raise _Halt(
                "interrupted_risk_off_port_failed",
                "interrupted_risk_off",
            )
        create_record = self.action_store.inspect(
            plan.action_claim(Slice3ActionKind.CREATE)
        )
        if (
            create_record is None
            or create_record.event is not Slice3ClaimEvent.OUTCOME
            or create_record.outcome is None
        ):
            raise _Halt(
                "interrupted_create_outcome_missing",
                "interrupted_risk_off",
            )
        opening: Slice3ExactOrderEvidence | None = None
        close: Slice3ExactOrderEvidence | None = None
        if create_record.outcome is Slice3MutationOutcome.REJECTED:
            dependency = {
                "schema_version": "slice3-create-rejection-retirement-v1",
                "plan_sha256": plan.plan_sha256,
                "create_record_sha256": create_record.record_sha256,
            }
            self._retire_if_claimed(
                plan=plan,
                action=Slice3ActionKind.CANCEL,
                reason_code="cancel_not_required_create_rejected",
                dependency=dependency,
                phase="interrupted_risk_off",
            )
            self._retire_if_claimed(
                plan=plan,
                action=Slice3ActionKind.CLOSE,
                reason_code="close_not_required_create_rejected",
                dependency=dependency,
                phase="interrupted_risk_off",
            )
        else:
            context.phase = "recovery_create_lookup"
            value = self._read(
                plan=plan,
                slot=Slice3ReadSlot.RECOVERY_OPENING_ORDER_BY_CLIENT_ID,
                delegate=lambda observed_at: (
                    port.resolve_exact_order_by_client_order_id(
                        client_order_id=plan.create.client_order_id,
                        observed_at=observed_at,
                    )
                ),
                failure_reason="recovery_create_lookup_failed",
                phase="recovery_create_lookup",
            )
            opening = self._validate_opening_evidence(
                value,
                plan=plan,
                source=Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP,
                unknown_create=True,
            )
            position = self._read(
                plan=plan,
                slot=Slice3ReadSlot.RECOVERY_POSITION,
                delegate=lambda observed_at: port.read_position(
                    observed_at=observed_at
                ),
                failure_reason="recovery_position_read_failed",
                phase="recovery_position",
            )
            if not isinstance(position, Slice3PositionObservation):
                raise _Halt(
                    "recovery_position_invalid",
                    "recovery_position",
                )
            cancel_record = self.action_store.inspect(
                plan.action_claim(Slice3ActionKind.CANCEL)
            )
            close_record = self.action_store.inspect(
                plan.action_claim(Slice3ActionKind.CLOSE)
            )
            if cancel_record is None or close_record is None:
                raise _Halt(
                    "recovery_action_state_missing",
                    "interrupted_risk_off",
                )
            directive: Slice3Directive | None = None
            if close_record.event is Slice3ClaimEvent.OUTCOME:
                if (
                    close_record.outcome is Slice3MutationOutcome.REJECTED
                    or opening.observation.status
                    not in {
                        OrderStatus.FILLED,
                        OrderStatus.CANCELLED,
                        OrderStatus.EXPIRED,
                        OrderStatus.FAILED,
                    }
                    or opening.observation.filled <= 0
                ):
                    raise _Halt(
                        "recovery_close_outcome_unrestored",
                        "recovery_close_lookup",
                    )
                value = self._read(
                    plan=plan,
                    slot=(Slice3ReadSlot.RECOVERY_CLOSE_ORDER_BY_CLIENT_ID),
                    delegate=lambda observed_at: (
                        port.resolve_exact_close_order_by_client_order_id(
                            client_order_id=plan.close_client_order_id,
                            observed_at=observed_at,
                            expected_close_size=opening.observation.filled,
                        )
                    ),
                    failure_reason="recovery_close_lookup_failed",
                    phase="recovery_close_lookup",
                )
                if not isinstance(value, Slice3ExactOrderEvidence) or not (
                    value.observation.resolution_source
                    is Slice3OrderResolutionSource.EXACT_CLIENT_ORDER_ID_LOOKUP
                    and value.observation.exact_client_order_match_count == 1
                ):
                    raise _Halt(
                        "recovery_close_not_uniquely_resolved",
                        "recovery_close_lookup",
                    )
                close = value
                if cancel_record.event is Slice3ClaimEvent.CLAIM:
                    self._retire(
                        plan=plan,
                        action=Slice3ActionKind.CANCEL,
                        reason_code="cancel_not_required_filled_branch",
                        dependency={
                            "schema_version": "slice3-cancel-retirement-v1",
                            "plan_sha256": plan.plan_sha256,
                            "opening_order": opening.sanitized_evidence(),
                            "close_record_sha256": close_record.record_sha256,
                        },
                    )
                elif cancel_record.event not in {
                    Slice3ClaimEvent.OUTCOME,
                    Slice3ClaimEvent.RETIRED,
                }:
                    raise _Halt(
                        "recovery_cancel_state_invalid",
                        "recovery_close_lookup",
                    )
            elif close_record.event in {
                Slice3ClaimEvent.CLAIM,
                Slice3ClaimEvent.RETIRED,
            }:
                directive = self._decision(
                    plan=plan,
                    opening=opening,
                    position=position,
                    create_outcome=create_record.outcome,
                    now=self._now(),
                )
            else:
                raise _Halt(
                    "recovery_close_state_invalid",
                    "interrupted_risk_off",
                )

            if directive is None:
                pass
            elif directive.kind in {
                Slice3DirectiveKind.CANCEL_OPEN,
                Slice3DirectiveKind.CANCEL_RESIDUAL,
            }:
                if (
                    cancel_record.event is not Slice3ClaimEvent.CLAIM
                    or close_record.event is not Slice3ClaimEvent.CLAIM
                ):
                    raise _Halt(
                        "recovery_cancel_already_terminal_order_active",
                        "recovery_cancel",
                    )
                context.phase = "recovery_cancel"
                self.gate.execute_cancel(
                    plan,
                    order=opening.observation,
                    position=position,
                    port_factory=lambda: port,
                    now=self._now(),
                )
                exchange_order_id = opening.observation.exchange_order_id
                if exchange_order_id is None:
                    raise _Halt(
                        "recovery_cancel_identity_missing",
                        "recovery_cancel",
                    )
                value = self._read(
                    plan=plan,
                    slot=Slice3ReadSlot.RECOVERY_POST_CANCEL_TERMINAL_ORDER,
                    delegate=lambda observed_at: port.read_exact_order(
                        client_order_id=plan.create.client_order_id,
                        exchange_order_id=exchange_order_id,
                        observed_at=observed_at,
                    ),
                    failure_reason="recovery_post_cancel_read_failed",
                    phase="recovery_post_cancel",
                )
                opening = self._validate_opening_evidence(
                    value,
                    plan=plan,
                    source=Slice3OrderResolutionSource.AUTHORITATIVE_ORDER_READ,
                    unknown_create=False,
                )
                position = self._read(
                    plan=plan,
                    slot=Slice3ReadSlot.RECOVERY_POST_CANCEL_POSITION,
                    delegate=lambda observed_at: port.read_position(
                        observed_at=observed_at
                    ),
                    failure_reason="recovery_pre_close_position_failed",
                    phase="recovery_pre_close_position",
                )
                if not isinstance(position, Slice3PositionObservation):
                    raise _Halt(
                        "recovery_position_invalid",
                        "recovery_pre_close_position",
                    )
                directive = self._decision(
                    plan=plan,
                    opening=opening,
                    position=position,
                    create_outcome=create_record.outcome,
                    now=self._now(),
                )
                if directive.kind is Slice3DirectiveKind.CLOSE_EXACT_DELTA:
                    market = self._read(
                        plan=plan,
                        slot=Slice3ReadSlot.RECOVERY_MARKET,
                        delegate=lambda observed_at: port.read_market_reference(
                            observed_at=observed_at
                        ),
                        failure_reason="recovery_market_read_failed",
                        phase="recovery_market",
                    )
                    if not isinstance(market, Slice3MarketReference):
                        raise _Halt(
                            "recovery_market_invalid",
                            "recovery_market",
                        )
                    context.phase = "recovery_pre_close_open_orders"
                    open_orders = self._read(
                        plan=plan,
                        slot=(
                            Slice3ReadSlot.RECOVERY_PRE_CLOSE_OPEN_ORDERS
                        ),
                        delegate=lambda observed_at: port.prove_zero_open_orders(
                            observed_at=observed_at
                        ),
                        failure_reason=(
                            "recovery_pre_close_open_orders_read_failed"
                        ),
                        phase="recovery_pre_close_open_orders",
                    )
                    if not isinstance(open_orders, Slice3OpenOrderZeroProof):
                        raise _Halt(
                            "recovery_pre_close_open_orders_invalid",
                            "recovery_pre_close_open_orders",
                        )
                    close_result = self.gate.execute_close(
                        plan,
                        order=opening.observation,
                        position=position,
                        market=market,
                        open_orders=open_orders,
                        port_factory=lambda: port,
                        now=self._now(),
                    )
                    close = self._read_close_result(
                        context=context,
                        plan=plan,
                        port=port,
                        directive=directive,
                        result=close_result,
                        recovery=True,
                    )
                elif directive.kind in {
                    Slice3DirectiveKind.COMPLETE_FLAT,
                    Slice3DirectiveKind.COMPLETE_REJECTED,
                }:
                    self._retire(
                        plan=plan,
                        action=Slice3ActionKind.CLOSE,
                        reason_code="close_not_required_zero_exposure",
                        dependency={
                            "schema_version": "slice3-zero-close-retirement-v1",
                            "plan_sha256": plan.plan_sha256,
                            "opening_order": opening.sanitized_evidence(),
                        },
                    )
                else:
                    raise _Halt(
                        "recovery_post_cancel_not_terminal",
                        "recovery_post_cancel",
                    )
            elif directive.kind is Slice3DirectiveKind.CLOSE_EXACT_DELTA:
                if close_record.event is not Slice3ClaimEvent.CLAIM:
                    raise _Halt(
                        "recovery_close_claim_consumed",
                        "recovery_close",
                    )
                if cancel_record.event not in {
                    Slice3ClaimEvent.CLAIM,
                    Slice3ClaimEvent.OUTCOME,
                }:
                    raise _Halt(
                        "recovery_cancel_state_invalid",
                        "recovery_close",
                    )
                close = self._close(
                    context=context,
                    plan=plan,
                    opening=opening,
                    create_outcome=create_record.outcome,
                    cancel_was_called=(cancel_record.event is Slice3ClaimEvent.OUTCOME),
                    position=position,
                    recovery=True,
                )
            elif directive.kind in {
                Slice3DirectiveKind.COMPLETE_FLAT,
                Slice3DirectiveKind.COMPLETE_REJECTED,
            }:
                if cancel_record.event is Slice3ClaimEvent.CLAIM:
                    self._retire(
                        plan=plan,
                        action=Slice3ActionKind.CANCEL,
                        reason_code="cancel_not_required_terminal_branch",
                        dependency={
                            "schema_version": ("slice3-terminal-cancel-retirement-v1"),
                            "plan_sha256": plan.plan_sha256,
                            "opening_order": opening.sanitized_evidence(),
                        },
                    )
                elif cancel_record.event not in {
                    Slice3ClaimEvent.OUTCOME,
                    Slice3ClaimEvent.RETIRED,
                }:
                    raise _Halt(
                        "recovery_cancel_state_invalid",
                        "interrupted_risk_off",
                    )
                self._retire_if_claimed(
                    plan=plan,
                    action=Slice3ActionKind.CLOSE,
                    reason_code="close_not_required_zero_exposure",
                    dependency={
                        "schema_version": "slice3-zero-close-retirement-v1",
                        "plan_sha256": plan.plan_sha256,
                        "opening_order": opening.sanitized_evidence(),
                    },
                    phase="interrupted_risk_off",
                )
            else:
                raise _Halt(
                    "recovery_branch_not_terminal",
                    "interrupted_risk_off",
                )

        final = self._final_reconciliation(
            context=context,
            plan=plan,
            recovery=True,
        )
        if (
            final.incomplete
            or final.position is None
            or final.open_orders is None
            or final.margin is None
        ):
            raise _Halt(
                "final_reconciliation_incomplete",
                "final_reconciliation",
            )
        read_hash = self._required_journal_sha256(self.read_journal)
        self._required_journal_sha256(self.action_store)
        try:
            return Slice3TerminalRoundtripEvidence.build(
                plan=plan,
                opening_order=opening,
                close_order=close,
                final_position=final.position,
                final_open_orders=final.open_orders,
                final_margin=final.margin,
                create_action=self._action_binding(
                    plan=plan,
                    action=Slice3ActionKind.CREATE,
                ),
                cancel_action=self._action_binding(
                    plan=plan,
                    action=Slice3ActionKind.CANCEL,
                ),
                close_action=self._action_binding(
                    plan=plan,
                    action=Slice3ActionKind.CLOSE,
                ),
                read_journal_sha256=read_hash,
                completed_at=self._now(),
            )
        except _Halt:
            raise
        except Exception:
            raise _Halt(
                "terminal_evidence_invalid",
                "terminal_evidence",
            ) from None

    @staticmethod
    def _generic_reason(phase: str) -> str:
        return {
            "claim_reservation": "action_claim_reservation_failed",
            "port_construction": "port_construction_failed",
            "create_execution": "create_execution_failed",
            "cancel_execution": "cancel_execution_failed",
            "close_execution": "close_execution_failed",
            "terminal_evidence": "terminal_evidence_invalid",
        }.get(phase, "orchestration_internal_failure")

    def run(
        self,
        *,
        plan: Slice3Plan,
        activation_store: _ActivationStore,
        expected_activation_manifest_sha256: str,
    ) -> Slice3OrchestrationResult:
        """Run the one finite attempt or return its durable sanitized halt."""

        now = self._now()
        seal = self._read_activation(
            plan=plan,
            activation_store=activation_store,
            expected_manifest_sha256=expected_activation_manifest_sha256,
            now=now,
        )
        create_record = self.action_store.inspect(
            plan.action_claim(Slice3ActionKind.CREATE)
        )
        risk_off = bool(
            create_record is not None
            and create_record.event
            in {
                Slice3ClaimEvent.EXCHANGE_BOUNDARY,
                Slice3ClaimEvent.OUTCOME,
            }
        )
        try:
            if risk_off:
                plan.validate_risk_off_at(now)
            else:
                plan.validate_at(now)
        except Exception:
            raise Slice3OrchestrationError(
                "slice3_activation_binding_invalid"
            ) from None
        lease = self.terminal_store.reserve(
            plan_sha256=plan.plan_sha256,
            activation_manifest_sha256=seal.manifest_sha256,
            now=self._now(),
        )
        if lease.recovered:
            try:
                return self._recover_interrupted_attempt(
                    lease=lease,
                    plan=plan,
                    seal=seal,
                )
            finally:
                lease.release()
        context = _ExecutionContext()
        try:
            try:
                evidence = self._execute(
                    context=context,
                    plan=plan,
                    seal=seal,
                )
                context.phase = "terminal_evidence"
                read_hash = self._required_journal_sha256(self.read_journal)
                action_hash = self._required_journal_sha256(self.action_store)
            except _Halt as exc:
                reason_code = exc.reason_code
                phase = exc.phase
            except Exception:
                reason_code = self._generic_reason(context.phase)
                phase = context.phase
            else:
                artifact_hash = self.terminal_store.complete_restored(
                    lease=lease,
                    plan_sha256=plan.plan_sha256,
                    activation_manifest_sha256=seal.manifest_sha256,
                    now=self._now(),
                    evidence=evidence,
                    action_journal_sha256=action_hash,
                    read_journal_sha256=read_hash,
                )
                return Slice3OrchestrationResult(
                    status=Slice3OrchestrationStatus.RESTORED_BASELINE,
                    terminal_evidence=evidence,
                    reason_code="restored_baseline",
                    terminal_artifact_sha256=artifact_hash,
                )

            if context.mutation_started and context.port is not None:
                self._terminalize_recovery_boundaries(plan=plan)
                recovery_context = _ExecutionContext(
                    phase="ordinary_risk_off",
                    port=context.port,
                    mutation_started=True,
                )
                try:
                    recovery_evidence = self._execute_recovered_create_risk_off(
                        context=recovery_context,
                        plan=plan,
                        seal=seal,
                    )
                    read_hash = self._required_journal_sha256(self.read_journal)
                    action_hash = self._required_journal_sha256(self.action_store)
                except _Halt as exc:
                    reason_code = exc.reason_code
                    phase = exc.phase
                except Exception:
                    reason_code = "ordinary_risk_off_failed"
                    phase = "ordinary_risk_off"
                else:
                    artifact_hash = self.terminal_store.complete_restored(
                        lease=lease,
                        plan_sha256=plan.plan_sha256,
                        activation_manifest_sha256=seal.manifest_sha256,
                        now=self._now(),
                        evidence=recovery_evidence,
                        action_journal_sha256=action_hash,
                        read_journal_sha256=read_hash,
                    )
                    return Slice3OrchestrationResult(
                        status=(Slice3OrchestrationStatus.RESTORED_BASELINE),
                        terminal_evidence=recovery_evidence,
                        reason_code="restored_baseline",
                        terminal_artifact_sha256=artifact_hash,
                    )
                if not recovery_context.final_reconciliation_attempted:
                    self._final_reconciliation(
                        context=recovery_context,
                        plan=plan,
                        recovery=True,
                    )
                context = recovery_context

            if (
                context.mutation_started
                and not context.final_reconciliation_attempted
                and context.port is not None
            ):
                self._final_reconciliation(context=context, plan=plan)
            self._retire_halt_claims(plan=plan, reason_code=reason_code)
            read_hash = self._safe_journal_sha256(self.read_journal)
            action_hash = self._safe_journal_sha256(self.action_store)
            halted_evidence = self._halted_reconciliation_evidence(
                context=context,
                plan=plan,
            )
            artifact_hash = self.terminal_store.complete_halted(
                lease=lease,
                plan=plan,
                activation_manifest_sha256=seal.manifest_sha256,
                now=self._now(),
                reason_code=reason_code,
                phase=phase,
                evidence=halted_evidence,
                action_journal_sha256=action_hash,
                read_journal_sha256=read_hash,
            )
            return Slice3OrchestrationResult(
                status=Slice3OrchestrationStatus.HALTED,
                terminal_evidence=halted_evidence,
                reason_code=reason_code,
                terminal_artifact_sha256=artifact_hash,
            )
        finally:
            lease.release()


__all__ = [
    "FileSlice3TerminalArtifactStore",
    "Slice3OrchestrationError",
    "Slice3OrchestrationResult",
    "Slice3OrchestrationStatus",
    "Slice3TerminalAttemptLease",
    "Slice3TerminalArtifactError",
    "Slice3TerminalRoundtripOrchestrator",
]
