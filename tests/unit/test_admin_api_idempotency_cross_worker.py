"""Cross-worker safety tests for Admin API command idempotency."""

from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path
from typing import Any

from application.admin_api.idempotency import (
    FileIdempotencyStore,
    IdempotencyRecord,
    hashed_interprocess_lock,
    make_payload_hash,
)
from application.admin_api.command_service import SpotProfileOrderAdmissionCoordinator
from core.enums import AdminApiCommandStatus, AdminApiIdempotencyDecision


IDEMPOTENCY_KEY = "shared-command-key"
PAYLOAD_HASH = make_payload_hash({"command": "one-bounded-side-effect"})
PRIVATE_PROFILE_ID = "11111111-2222-4333-8444-555555555555"


class _PausedAppendStore(FileIdempotencyStore):
    """Pause one append transaction before its durable JSONL write."""

    def __init__(self, path: str, entered: Any, release: Any) -> None:
        super().__init__(path)
        self._entered = entered
        self._release = release

    def _externalize_large_response(
        self,
        record: IdempotencyRecord,
    ) -> IdempotencyRecord:
        self._entered.set()
        if not self._release.wait(timeout=10):
            raise TimeoutError("append release timed out")
        return super()._externalize_large_response(record)


def _run_same_command(
    *,
    store_path: str,
    side_effect_path: str,
    ready_queue: Any,
    start_event: Any,
    result_queue: Any,
) -> None:
    """Execute the same command boundary in an independent worker process."""

    store = FileIdempotencyStore(store_path)
    ready_queue.put("ready")
    if not start_event.wait(timeout=10):
        result_queue.put("start_timeout")
        return

    with store.command_execution(idempotency_key=IDEMPOTENCY_KEY):
        check = store.evaluate(
            idempotency_key=IDEMPOTENCY_KEY,
            payload_hash=PAYLOAD_HASH,
        )
        if check.decision == AdminApiIdempotencyDecision.REPLAY:
            result_queue.put("replayed")
            return
        if check.decision != AdminApiIdempotencyDecision.NEW:
            result_queue.put(check.decision.value)
            return

        # Keep the pre-fix evaluate -> side effect window open long enough for
        # both workers to observe NEW. The command lock must cover this entire
        # interval, not merely the final append-only record write.
        time.sleep(0.25)
        with Path(side_effect_path).open("a", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            os.fsync(handle.fileno())
        store.put_record(
            IdempotencyRecord(
                idempotency_key=IDEMPOTENCY_KEY,
                payload_hash=PAYLOAD_HASH,
                status=AdminApiCommandStatus.ACCEPTED,
                response={"status": "accepted"},
                endpoint="POST /synthetic-command",
            )
        )
        result_queue.put("executed")


def _hold_profile_claim(
    *,
    lock_root: str,
    command_key: str,
    ready_queue: Any,
    start_event: Any,
    result_queue: Any,
    active_count: Any,
    peak_count: Any,
) -> None:
    """Model two distinct idempotency keys targeting one Spot profile."""

    ready_queue.put("ready")
    if not start_event.wait(timeout=10):
        result_queue.put("start_timeout")
        return
    try:
        coordinator = SpotProfileOrderAdmissionCoordinator(lock_root=lock_root)
        with coordinator.claim(PRIVATE_PROFILE_ID):
            with active_count.get_lock():
                active_count.value += 1
                peak_count.value = max(peak_count.value, active_count.value)
            time.sleep(0.25)
            with active_count.get_lock():
                active_count.value -= 1
        result_queue.put(command_key)
    except BaseException as exc:  # pragma: no cover - parent asserts details
        result_queue.put(f"error:{type(exc).__name__}")


def _pause_distinct_key_append(
    *,
    store_path: str,
    entered: Any,
    release: Any,
    result_queue: Any,
) -> None:
    try:
        store = _PausedAppendStore(store_path, entered, release)
        store.put_record(
            IdempotencyRecord(
                idempotency_key="writer-key",
                payload_hash=make_payload_hash({"command": "writer"}),
                status=AdminApiCommandStatus.ACCEPTED,
                response={"status": "accepted"},
                endpoint="POST /writer",
            )
        )
        result_queue.put("writer_finished")
    except BaseException as exc:  # pragma: no cover - parent asserts details
        result_queue.put(f"writer_error:{type(exc).__name__}")


def _read_distinct_key_during_append(
    *,
    store_path: str,
    started: Any,
    finished: Any,
    result_queue: Any,
) -> None:
    try:
        store = FileIdempotencyStore(store_path)
        started.set()
        decision = store.evaluate(
            idempotency_key="reader-key",
            payload_hash=make_payload_hash({"command": "reader"}),
        ).decision
        result_queue.put(f"reader:{decision.value}")
    except BaseException as exc:  # pragma: no cover - parent asserts details
        result_queue.put(f"reader_error:{type(exc).__name__}")
    finally:
        finished.set()


def _exit_while_holding_opaque_lock(*, lock_root: str, entered: Any) -> None:
    with hashed_interprocess_lock(
        lock_root=lock_root,
        namespace="synthetic-crash-release",
        identity="private-crash-lock-identity",
    ):
        entered.set()
        os._exit(23)


def test_command_execution_serializes_same_key_across_worker_processes(
    tmp_path: Path,
) -> None:
    """Only one worker may cross the side-effect boundary for one key/body."""

    context = multiprocessing.get_context(
        "spawn" if os.name == "nt" else "fork"
    )
    ready_queue = context.Queue()
    result_queue = context.Queue()
    start_event = context.Event()
    store_path = tmp_path / "idempotency.jsonl"
    side_effect_path = tmp_path / "side-effects.log"
    workers = [
        context.Process(
            target=_run_same_command,
            kwargs={
                "store_path": str(store_path),
                "side_effect_path": str(side_effect_path),
                "ready_queue": ready_queue,
                "start_event": start_event,
                "result_queue": result_queue,
            },
        )
        for _ in range(2)
    ]

    for worker in workers:
        worker.start()
    assert [ready_queue.get(timeout=10) for _ in workers] == ["ready", "ready"]
    start_event.set()
    outcomes = sorted(result_queue.get(timeout=10) for _ in workers)
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0

    assert outcomes == ["executed", "replayed"]
    assert len(side_effect_path.read_text(encoding="utf-8").splitlines()) == 1
    rows = store_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    lock_names = [path.name for path in tmp_path.glob("*.lock")]
    assert lock_names
    assert all(IDEMPOTENCY_KEY not in name for name in lock_names)


def test_spot_profile_claim_serializes_distinct_keys_across_worker_processes(
    tmp_path: Path,
) -> None:
    """Different command keys cannot share one profile mutation boundary."""

    context = multiprocessing.get_context(
        "spawn" if os.name == "nt" else "fork"
    )
    ready_queue = context.Queue()
    result_queue = context.Queue()
    start_event = context.Event()
    active_count = context.Value("i", 0)
    peak_count = context.Value("i", 0)
    lock_root = tmp_path / "locks"
    workers = [
        context.Process(
            target=_hold_profile_claim,
            kwargs={
                "lock_root": str(lock_root),
                "command_key": command_key,
                "ready_queue": ready_queue,
                "start_event": start_event,
                "result_queue": result_queue,
                "active_count": active_count,
                "peak_count": peak_count,
            },
        )
        for command_key in ("command-key-a", "command-key-b")
    ]

    for worker in workers:
        worker.start()
    assert [ready_queue.get(timeout=10) for _ in workers] == ["ready", "ready"]
    start_event.set()
    outcomes = sorted(result_queue.get(timeout=10) for _ in workers)
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0

    assert outcomes == ["command-key-a", "command-key-b"]
    assert peak_count.value == 1
    lock_names = [path.name for path in lock_root.glob("*.lock")]
    assert len(lock_names) == 1
    assert PRIVATE_PROFILE_ID not in lock_names[0]


def test_store_serializes_distinct_key_append_and_read_across_workers(
    tmp_path: Path,
) -> None:
    """A reader cannot observe another key's partially persisted transaction."""

    context = multiprocessing.get_context(
        "spawn" if os.name == "nt" else "fork"
    )
    append_entered = context.Event()
    append_release = context.Event()
    reader_started = context.Event()
    reader_finished = context.Event()
    result_queue = context.Queue()
    store_path = tmp_path / "idempotency.jsonl"
    writer = context.Process(
        target=_pause_distinct_key_append,
        kwargs={
            "store_path": str(store_path),
            "entered": append_entered,
            "release": append_release,
            "result_queue": result_queue,
        },
    )
    reader = context.Process(
        target=_read_distinct_key_during_append,
        kwargs={
            "store_path": str(store_path),
            "started": reader_started,
            "finished": reader_finished,
            "result_queue": result_queue,
        },
    )

    writer.start()
    assert append_entered.wait(timeout=10)
    reader.start()
    assert reader_started.wait(timeout=10)
    reader_was_blocked = reader_finished.wait(timeout=0.25) is False
    append_release.set()
    outcomes = sorted(result_queue.get(timeout=10) for _ in range(2))
    for worker in (writer, reader):
        worker.join(timeout=10)
        assert worker.exitcode == 0

    assert reader_was_blocked is True
    assert outcomes == ["reader:new", "writer_finished"]
    persisted = FileIdempotencyStore(store_path).get_record("writer-key")
    assert persisted is not None
    assert persisted.response == {"status": "accepted"}


def test_opaque_interprocess_lock_is_released_when_worker_exits(
    tmp_path: Path,
) -> None:
    """The OS lock cannot remain held after an owning worker is lost."""

    context = multiprocessing.get_context(
        "spawn" if os.name == "nt" else "fork"
    )
    entered = context.Event()
    lock_root = tmp_path / "locks"
    worker = context.Process(
        target=_exit_while_holding_opaque_lock,
        kwargs={"lock_root": str(lock_root), "entered": entered},
    )

    worker.start()
    assert entered.wait(timeout=10)
    worker.join(timeout=10)
    assert worker.exitcode == 23

    with hashed_interprocess_lock(
        lock_root=lock_root,
        namespace="synthetic-crash-release",
        identity="private-crash-lock-identity",
    ):
        pass
    lock_names = [path.name for path in lock_root.glob("*.lock")]
    assert len(lock_names) == 1
    assert "private-crash-lock-identity" not in lock_names[0]
