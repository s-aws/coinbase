"""Idempotency contract helpers for future durable Admin API commands."""

from __future__ import annotations

import hashlib
import gzip
import json
import os
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator, ParamSpec, TypeVar
from weakref import WeakValueDictionary

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AdminApiCommandStatus,
    AdminApiIdempotencyDecision,
    AdminApiIdempotencyResponseStorage,
)


MAX_INLINE_IDEMPOTENCY_RESPONSE_BYTES = 1_000_000
MAX_IDEMPOTENCY_RESPONSE_BLOB_BYTES = 50_000_000
IDEMPOTENCY_RESPONSE_READ_CHUNK_BYTES = 64 * 1024
IDEMPOTENCY_LOG_PATH_ENV = "COINBASE_ADMIN_API_IDEMPOTENCY_LOG_PATH"
DEFAULT_IDEMPOTENCY_LOG_PATH = Path("runtime_state") / "admin_api_idempotency.jsonl"


_COMMAND_EXECUTION_LOCKS_GUARD = RLock()
_COMMAND_EXECUTION_LOCKS: WeakValueDictionary = WeakValueDictionary()
_CommandParameters = ParamSpec("_CommandParameters")
_CommandResult = TypeVar("_CommandResult")


@contextmanager
def _interprocess_file_lock(path: Path) -> Iterator[None]:
    """Serialize a bounded transaction across backend worker processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            # ``msvcrt.locking`` locks a byte range from the current file
            # position. Materialize byte zero so the same range is valid on
            # every supported Windows CRT instead of relying on beyond-EOF
            # locking behavior for a newly created empty file.
            if os.fstat(handle.fileno()).st_size < 1:
                handle.truncate(1)
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def hashed_interprocess_lock(
    *,
    lock_root: Path | str,
    namespace: str,
    identity: str,
) -> Iterator[None]:
    """Lock one opaque identity across workers without exposing it in a path.

    The operating system releases the advisory lock if a worker exits. The
    empty lock file may remain and is safe to reuse. Callers must keep durable
    fail-closed claim evidence around any external side effect because a lock
    coordinates execution but is not itself a transaction journal.
    """

    normalized_namespace = str(namespace or "").strip()
    normalized_identity = str(identity or "").strip()
    if not normalized_namespace or not normalized_identity:
        raise ValueError("A non-empty lock namespace and identity are required.")
    digest = hashlib.sha256(
        f"{normalized_namespace}\0{normalized_identity}".encode("utf-8")
    ).hexdigest()
    lock_path = Path(lock_root).resolve() / f".admin-api-{digest}.lock"
    with _interprocess_file_lock(lock_path):
        yield


class IdempotencyRecord(BaseModel):
    """Stored evidence for one idempotent command request."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    client_order_id: str | None = None
    stealth_order_id: str | None = None
    status: AdminApiCommandStatus
    response: dict[str, Any] = Field(default_factory=dict)
    response_storage: AdminApiIdempotencyResponseStorage = (
        AdminApiIdempotencyResponseStorage.INLINE
    )
    response_blob_path: str | None = None
    response_blob_sha256: str | None = None
    response_blob_compression: str | None = None
    actor_id: str | None = None
    endpoint: str | None = None


class IdempotencyCheck(BaseModel):
    """Decision returned when a command is compared with stored evidence."""

    model_config = ConfigDict(extra="forbid")

    decision: AdminApiIdempotencyDecision
    record: IdempotencyRecord | None = None


def make_payload_hash(payload: Any) -> str:
    """Return a deterministic SHA-256 hash for JSON-compatible payloads."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_idempotency(
    *,
    existing: IdempotencyRecord | None,
    idempotency_key: str,
    payload_hash: str,
) -> IdempotencyCheck:
    """Compare incoming command evidence against an existing record."""

    if existing is None:
        return IdempotencyCheck(decision=AdminApiIdempotencyDecision.NEW)
    if existing.idempotency_key != idempotency_key:
        return IdempotencyCheck(decision=AdminApiIdempotencyDecision.NEW)
    if existing.payload_hash == payload_hash:
        return IdempotencyCheck(
            decision=AdminApiIdempotencyDecision.REPLAY,
            record=existing,
        )
    return IdempotencyCheck(
        decision=AdminApiIdempotencyDecision.CONFLICT,
        record=existing,
    )


class FileIdempotencyStore:
    """Append-only JSONL idempotency store for Admin API command requests.

    This is intentionally dependency-injectable. The route contract depends on
    the store interface, not the file implementation, so a PostgreSQL-backed
    repository can replace it without creating a second command behavior path.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_idempotency_store_path(path)
        self._lock = RLock()

    @contextmanager
    def command_execution(
        self,
        *,
        idempotency_key: str,
    ) -> Iterator[None]:
        """Serialize one key across workers through final durable persistence.

        Route handlers hold this boundary over idempotency evaluation, command
        admission, any external side effect, audit, and response persistence.
        The process-local lock avoids duplicate contenders in one worker; the
        opaque file lock provides the same exclusion between workers.
        """

        resolved_store_path = self.path.resolve()
        lock_identity = (str(resolved_store_path), idempotency_key)
        with _COMMAND_EXECUTION_LOCKS_GUARD:
            execution_lock = _COMMAND_EXECUTION_LOCKS.get(lock_identity)
            if execution_lock is None:
                execution_lock = RLock()
                _COMMAND_EXECUTION_LOCKS[lock_identity] = execution_lock
        with execution_lock:
            with hashed_interprocess_lock(
                lock_root=resolved_store_path.parent,
                namespace=f"admin-command:{resolved_store_path.name}",
                identity=idempotency_key,
            ):
                yield

    @contextmanager
    def endpoint_claim_execution(self, *, endpoint: str) -> Iterator[None]:
        """Serialize one endpoint-wide claim across store instances/workers."""

        endpoint_digest = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
        lock_path = self.path.parent / (
            f"{self.path.name}.{endpoint_digest}.claim.lock"
        )
        with self._lock:
            with _interprocess_file_lock(lock_path):
                yield

    @property
    def _response_blob_dir(self) -> Path:
        return self.path.parent / f"{self.path.stem}_responses"

    @contextmanager
    def _store_access(self) -> Iterator[None]:
        """Exclude cross-worker JSONL/blob reads from append transactions."""

        resolved_store_path = self.path.resolve()
        with hashed_interprocess_lock(
            lock_root=resolved_store_path.parent,
            namespace="admin-idempotency-store-access",
            identity=str(resolved_store_path),
        ):
            yield

    def _response_blob_path(self, record: IdempotencyRecord) -> Path:
        if not record.response_blob_path:
            raise ValueError("Missing idempotency response blob path.")
        blob_path = Path(record.response_blob_path)
        if not blob_path.is_absolute():
            blob_path = self.path.parent / blob_path
        resolved_parent = blob_path.parent.resolve()
        allowed_parent = self._response_blob_dir.resolve()
        if resolved_parent != allowed_parent:
            raise ValueError("Idempotency response blob path is outside the store.")
        return blob_path

    def _ensure_blob_size_within_limit(self, *, byte_count: int, context: str) -> None:
        if byte_count > MAX_IDEMPOTENCY_RESPONSE_BLOB_BYTES:
            raise ValueError(
                "Idempotency response blob exceeds bounded idempotency storage "
                f"for {context}: {byte_count} bytes exceeds "
                f"{MAX_IDEMPOTENCY_RESPONSE_BLOB_BYTES} bytes. Move large "
                "diagnostic evidence to a read endpoint and persist only the "
                "bounded command response."
            )

    def _gzip_uncompressed_size_hint(self, blob_path: Path) -> int | None:
        """Return gzip trailer ISIZE when available without hydrating the blob."""

        try:
            if blob_path.stat().st_size < 4:
                return None
            with blob_path.open("rb") as handle:
                handle.seek(-4, 2)
                return int.from_bytes(handle.read(4), "little")
        except OSError:
            return None

    def _read_gzip_response_with_limit(self, blob_path: Path, *, context: str) -> bytes:
        chunks: list[bytes] = []
        byte_count = 0
        with gzip.open(blob_path, "rb") as handle:
            while True:
                chunk = handle.read(IDEMPOTENCY_RESPONSE_READ_CHUNK_BYTES)
                if not chunk:
                    break
                byte_count += len(chunk)
                self._ensure_blob_size_within_limit(
                    byte_count=byte_count,
                    context=context,
                )
                chunks.append(chunk)
        return b"".join(chunks)

    def _externalize_large_response(self, record: IdempotencyRecord) -> IdempotencyRecord:
        if (
            not record.response
            or record.response_storage != AdminApiIdempotencyResponseStorage.INLINE
        ):
            return record
        encoded_response = json.dumps(
            record.response,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        if len(encoded_response) <= MAX_INLINE_IDEMPOTENCY_RESPONSE_BYTES:
            return record
        self._ensure_blob_size_within_limit(
            byte_count=len(encoded_response),
            context=f"write:{record.endpoint or record.idempotency_key}",
        )
        response_sha256 = hashlib.sha256(encoded_response).hexdigest()
        blob_name = (
            hashlib.sha256(
                f"{record.idempotency_key}:{record.payload_hash}".encode("utf-8")
            ).hexdigest()
            + ".json.gz"
        )
        blob_dir = self._response_blob_dir
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / blob_name
        with gzip.open(blob_path, "wb") as handle:
            handle.write(encoded_response)
        return record.model_copy(
            update={
                "response": {},
                "response_storage": AdminApiIdempotencyResponseStorage.GZIP_FILE,
                "response_blob_path": str(blob_path.relative_to(self.path.parent)),
                "response_blob_sha256": response_sha256,
                "response_blob_compression": "gzip",
            }
        )

    def _hydrate_response(self, record: IdempotencyRecord) -> IdempotencyRecord:
        if record.response_storage == AdminApiIdempotencyResponseStorage.INLINE:
            return record
        if record.response_storage != AdminApiIdempotencyResponseStorage.GZIP_FILE:
            raise ValueError(
                f"Unsupported idempotency response storage: {record.response_storage}"
            )
        blob_path = self._response_blob_path(record)
        if blob_path.stat().st_size > MAX_IDEMPOTENCY_RESPONSE_BLOB_BYTES:
            self._ensure_blob_size_within_limit(
                byte_count=blob_path.stat().st_size,
                context=f"compressed-read:{record.endpoint or record.idempotency_key}",
            )
        uncompressed_size_hint = self._gzip_uncompressed_size_hint(blob_path)
        if uncompressed_size_hint is not None:
            self._ensure_blob_size_within_limit(
                byte_count=uncompressed_size_hint,
                context=f"read:{record.endpoint or record.idempotency_key}",
            )
        encoded_response = self._read_gzip_response_with_limit(
            blob_path,
            context=f"hydrated-read:{record.endpoint or record.idempotency_key}",
        )
        self._ensure_blob_size_within_limit(
            byte_count=len(encoded_response),
            context=f"hydrated-read:{record.endpoint or record.idempotency_key}",
        )
        if record.response_blob_sha256:
            observed_sha256 = hashlib.sha256(encoded_response).hexdigest()
            if observed_sha256 != record.response_blob_sha256:
                raise ValueError("Idempotency response blob hash mismatch.")
        response = json.loads(encoded_response.decode("utf-8"))
        return record.model_copy(update={"response": response})

    def _load_latest_by_key(
        self,
        *,
        hydrate_responses: bool = True,
    ) -> dict[str, IdempotencyRecord]:
        records: dict[str, IdempotencyRecord] = {}
        if not self.path.exists():
            return records
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = IdempotencyRecord.model_validate_json(line)
                if hydrate_responses:
                    record = self._hydrate_response(record)
                records[record.idempotency_key] = record
        return records

    def get_record(self, idempotency_key: str) -> IdempotencyRecord | None:
        with self._lock:
            with self._store_access():
                return self._load_latest_by_key().get(idempotency_key)

    def has_record_for_endpoint(self, endpoint: str) -> bool:
        """Return whether any durable command record claimed an endpoint."""

        with self._lock:
            with self._store_access():
                return any(
                    record.endpoint == endpoint
                    for record in self._load_latest_by_key(
                        hydrate_responses=False
                    ).values()
                )

    def evaluate(self, *, idempotency_key: str, payload_hash: str) -> IdempotencyCheck:
        with self._lock:
            with self._store_access():
                existing = self._load_latest_by_key(hydrate_responses=False).get(
                    idempotency_key
                )
                check = evaluate_idempotency(
                    existing=existing,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                )
                if (
                    check.decision == AdminApiIdempotencyDecision.REPLAY
                    and check.record is not None
                ):
                    check.record = self._hydrate_response(check.record)
                return check

    def put_record(self, record: IdempotencyRecord) -> None:
        with self._lock:
            with self._store_access():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                record = self._externalize_large_response(record)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(record.model_dump_json() + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())


def serialize_idempotent_command(
    command_handler: Callable[_CommandParameters, _CommandResult],
) -> Callable[_CommandParameters, _CommandResult]:
    """Keep evaluate, command execution, and response persistence atomic per key."""

    @wraps(command_handler)
    def serialized(
        *args: _CommandParameters.args,
        **kwargs: _CommandParameters.kwargs,
    ) -> _CommandResult:
        idempotency_store = kwargs.get("idempotency_store")
        idempotency_key = kwargs.get("idempotency_key")
        if not isinstance(idempotency_store, FileIdempotencyStore):
            raise TypeError("FileIdempotencyStore is required for command execution.")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError("A non-empty idempotency key is required.")
        with idempotency_store.command_execution(
            idempotency_key=idempotency_key,
        ):
            return command_handler(*args, **kwargs)

    return serialized


def resolve_idempotency_store_path(path: Path | str | None = None) -> Path:
    """Return the configured durable idempotency store path."""

    configured_path = path or os.environ.get(IDEMPOTENCY_LOG_PATH_ENV)
    return Path(configured_path) if configured_path else DEFAULT_IDEMPOTENCY_LOG_PATH
