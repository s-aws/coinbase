from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from application.admin_api.futures_terminal_roundtrip_handoff_terminal import (
    ACCEPTED_HANDOFF_AUTHORIZATION_SHA256,
    ACCEPTED_HANDOFF_PREVIEW_ARTIFACT_TYPES,
    AcceptedHandoffArtifactError,
    AcceptedHandoffStage,
    AcceptedHandoffTerminalizer,
    FileAcceptedHandoffArtifactStore,
    halt_accepted_preview_handoff_offline,
)


_NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
_PREVIEW_GENERATION = 8
_PREVIEW_ARTIFACT_TYPE = "futures_exact_no_live_preview_slice_2r8"
_PREVIEW_FILE_SHA256 = "a" * 64
_PREVIEW_EVIDENCE_SHA256 = "b" * 64


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _terminalizer(path: Path) -> AcceptedHandoffTerminalizer:
    store = FileAcceptedHandoffArtifactStore(path)
    lease = store.reserve(
        preview_generation=_PREVIEW_GENERATION,
        preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )
    return AcceptedHandoffTerminalizer(store=store, lease=lease)


@pytest.mark.parametrize(
    ("stage", "reason"),
    (
        (AcceptedHandoffStage.PLAN, "accepted_handoff_plan_failed"),
        (AcceptedHandoffStage.ADMISSION, "accepted_handoff_admission_failed"),
        (AcceptedHandoffStage.ACTIVATION, "accepted_handoff_activation_failed"),
        (
            AcceptedHandoffStage.PORT_CONSTRUCTION,
            "accepted_handoff_port_construction_failed",
        ),
        (
            AcceptedHandoffStage.DELEGATION,
            "accepted_handoff_delegation_failed",
        ),
    ),
)
def test_each_pre_orchestration_failure_is_one_durable_halted_no_mutation_terminal(
    tmp_path: Path,
    stage: AcceptedHandoffStage,
    reason: str,
) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    terminalizer = _terminalizer(path)
    mutation_calls = 0

    def fail_before_mutation() -> None:
        nonlocal mutation_calls
        raise RuntimeError("synthetic private exception text")
        mutation_calls += 1  # pragma: no cover - proves the boundary is earlier

    with pytest.raises(RuntimeError, match="synthetic private exception text"):
        terminalizer.call(stage, fail_before_mutation, now=lambda: _NOW)

    assert mutation_calls == 0
    assert stat.S_IMODE(path.lstat().st_mode) == 0o400
    assert path.lstat().st_uid == os.geteuid()
    assert path.lstat().st_nlink == 1
    rows = _rows(path)
    assert len(rows) == 2
    assert [row["event"] for row in rows] == ["accepted_handoff_reserved", "terminal"]
    assert rows[1]["status"] == "halted"
    assert rows[1]["stage"] == stage.value
    assert rows[1]["reason_code"] == reason
    assert rows[1]["grants_exchange_action_authority"] is False
    assert rows[1]["coinbase_calls_permitted"] == 0
    assert rows[1]["raw_response_included"] is False
    assert rows[1]["identifier_values_included"] is False
    assert rows[1]["exception_text_included"] is False
    payload = path.read_text(encoding="utf-8")
    assert "synthetic private exception text" not in payload
    assert "client_order_id" not in payload
    assert "preview_id" not in payload
    with pytest.raises(
        AcceptedHandoffArtifactError,
        match="^accepted_handoff_terminal_already_completed$",
    ):
        terminalizer.call(stage, lambda: None, now=lambda: _NOW)
    assert len(_rows(path)) == 2


def test_successful_delegation_terminal_is_hash_only_and_one_use(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    store = FileAcceptedHandoffArtifactStore(path)
    terminalizer = _terminalizer(path)

    result = terminalizer.delegate(lambda: {"sanitized": True}, now=lambda: _NOW)

    assert result == {"sanitized": True}
    terminal = store.read_terminal()
    assert terminal["status"] == "delegated"
    assert terminal["stage"] == "delegation"
    assert terminal["reason_code"] == "accepted_handoff_delegated"
    assert terminal["preview_generation"] == _PREVIEW_GENERATION
    assert terminal["preview_artifact_type"] == _PREVIEW_ARTIFACT_TYPE
    assert terminal["preview_artifact_file_sha256"] == _PREVIEW_FILE_SHA256
    assert terminal["preview_evidence_sha256"] == _PREVIEW_EVIDENCE_SHA256
    assert terminal["authorization_sha256"] == ACCEPTED_HANDOFF_AUTHORIZATION_SHA256
    assert terminal["grants_exchange_action_authority"] is False
    assert terminal["coinbase_calls_permitted"] == 0

    with pytest.raises(
        AcceptedHandoffArtifactError,
        match="^accepted_handoff_attempt_consumed$",
    ):
        store.reserve(
            preview_generation=_PREVIEW_GENERATION,
            preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
            preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
            preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
            now=_NOW + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ("generation", "artifact_type"),
    tuple(ACCEPTED_HANDOFF_PREVIEW_ARTIFACT_TYPES.items()),
)
def test_each_authorized_preview_generation_has_one_exact_type(
    tmp_path: Path,
    generation: int,
    artifact_type: str,
) -> None:
    path = tmp_path / f"accepted-handoff-{generation}.jsonl"
    store = FileAcceptedHandoffArtifactStore(path)
    lease = store.reserve(
        preview_generation=generation,
        preview_artifact_type=artifact_type,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )
    store.complete_halted(
        lease=lease,
        stage=AcceptedHandoffStage.PLAN,
        now=_NOW,
    )

    terminal = store.read_terminal()
    assert terminal["preview_generation"] == generation
    assert terminal["preview_artifact_type"] == artifact_type


@pytest.mark.parametrize(
    ("generation", "artifact_type"),
    (
        (8, "futures_exact_no_live_preview_slice_2r9"),
        (9, "futures_exact_no_live_preview_slice_2r8"),
        (10, "futures_exact_no_live_preview_slice_2r9"),
        (7, "futures_exact_no_live_preview_slice_2r7"),
        (True, "futures_exact_no_live_preview_slice_2r8"),
    ),
)
def test_generation_and_artifact_type_mismatch_fails_before_reservation(
    tmp_path: Path,
    generation: object,
    artifact_type: str,
) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    with pytest.raises(
        AcceptedHandoffArtifactError,
        match="^accepted_handoff_preview_binding_invalid$",
    ):
        FileAcceptedHandoffArtifactStore(path).reserve(
            preview_generation=generation,
            preview_artifact_type=artifact_type,
            preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
            preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
            now=_NOW,
        )
    assert not path.exists()


def test_recovered_reservation_rejects_changed_preview_binding(tmp_path: Path) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    first_store = FileAcceptedHandoffArtifactStore(path)
    lease = first_store.reserve(
        preview_generation=_PREVIEW_GENERATION,
        preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )
    lease.release()

    with pytest.raises(
        AcceptedHandoffArtifactError,
        match="^accepted_handoff_binding_invalid$",
    ):
        FileAcceptedHandoffArtifactStore(path).reserve(
            preview_generation=9,
            preview_artifact_type="futures_exact_no_live_preview_slice_2r9",
            preview_artifact_file_sha256="c" * 64,
            preview_evidence_sha256="d" * 64,
            now=_NOW,
        )


def test_second_reserve_cannot_share_live_one_use_lease(tmp_path: Path) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    first_store = FileAcceptedHandoffArtifactStore(path)
    lease = first_store.reserve(
        preview_generation=_PREVIEW_GENERATION,
        preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )
    try:
        with pytest.raises(
            AcceptedHandoffArtifactError,
            match="^accepted_handoff_attempt_consumed$",
        ):
            FileAcceptedHandoffArtifactStore(path).reserve(
                preview_generation=_PREVIEW_GENERATION,
                preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
                preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
                preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
                now=_NOW,
            )
    finally:
        first_store.complete_halted(
            lease=lease,
            stage=AcceptedHandoffStage.DELEGATION,
            now=_NOW,
        )


def test_tampered_terminal_hash_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    terminalizer = _terminalizer(path)
    terminalizer.delegate(lambda: None, now=lambda: _NOW)
    rows = _rows(path)
    rows[1]["reason_code"] = "accepted_handoff_plan_failed"
    path.chmod(0o600)
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    path.chmod(0o400)

    with pytest.raises(
        AcceptedHandoffArtifactError,
        match="^accepted_handoff_artifact_invalid$",
    ):
        FileAcceptedHandoffArtifactStore(path).read_terminal()


def test_foreign_store_cannot_complete_another_store_lease(tmp_path: Path) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    owning_store = FileAcceptedHandoffArtifactStore(path)
    lease = owning_store.reserve(
        preview_generation=_PREVIEW_GENERATION,
        preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )
    foreign_store = FileAcceptedHandoffArtifactStore(path)

    with pytest.raises(
        AcceptedHandoffArtifactError,
        match="^accepted_handoff_attempt_lease_invalid$",
    ):
        foreign_store.complete_halted(
            lease=lease,
            stage=AcceptedHandoffStage.DELEGATION,
            now=_NOW,
        )
    owning_store.complete_halted(
        lease=lease,
        stage=AcceptedHandoffStage.DELEGATION,
        now=_NOW,
    )


@pytest.mark.parametrize("reservation_exists", (False, True))
def test_offline_halt_handles_missing_or_crash_left_reservation_without_calling_ports(
    tmp_path: Path,
    reservation_exists: bool,
) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    if reservation_exists:
        store = FileAcceptedHandoffArtifactStore(path)
        lease = store.reserve(
            preview_generation=9,
            preview_artifact_type="futures_exact_no_live_preview_slice_2r9",
            preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
            preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
            now=_NOW,
        )
        lease.release()
    preview_calls = 0
    mutation_calls = 0

    result = halt_accepted_preview_handoff_offline(
        path=path,
        preview_generation=9,
        preview_artifact_type="futures_exact_no_live_preview_slice_2r9",
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )

    assert preview_calls == 0
    assert mutation_calls == 0
    assert result.status == "halted"
    assert result.stage == "delegation"
    assert result.reason_code == "accepted_handoff_delegation_failed"
    assert result.artifact_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(_rows(path)) == 2


def test_offline_halt_is_idempotent_only_for_the_same_halted_binding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    kwargs = {
        "path": path,
        "preview_generation": 10,
        "preview_artifact_type": "futures_exact_no_live_preview_slice_2r10",
        "preview_artifact_file_sha256": _PREVIEW_FILE_SHA256,
        "preview_evidence_sha256": _PREVIEW_EVIDENCE_SHA256,
        "now": _NOW,
    }
    first = halt_accepted_preview_handoff_offline(**kwargs)
    second = halt_accepted_preview_handoff_offline(**kwargs)

    assert second == first
    assert len(_rows(path)) == 2


def test_completion_atomically_replaces_reservation_and_fsyncs(tmp_path: Path) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    store = FileAcceptedHandoffArtifactStore(path)
    lease = store.reserve(
        preview_generation=_PREVIEW_GENERATION,
        preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )
    reserved = path.lstat()

    artifact_sha256 = store.complete_halted(
        lease=lease,
        stage=AcceptedHandoffStage.ACTIVATION,
        now=_NOW + timedelta(milliseconds=1),
    )

    terminal = path.lstat()
    assert (terminal.st_dev, terminal.st_ino) != (reserved.st_dev, reserved.st_ino)
    assert artifact_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.read_bytes().endswith(b"\n")
    assert len(_rows(path)) == 2


def test_reservation_recovery_preserves_one_use_binding(tmp_path: Path) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    first = FileAcceptedHandoffArtifactStore(path)
    first_lease = first.reserve(
        preview_generation=_PREVIEW_GENERATION,
        preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW,
    )
    first_lease.release()

    recovered_store = FileAcceptedHandoffArtifactStore(path)
    recovered = recovered_store.reserve(
        preview_generation=_PREVIEW_GENERATION,
        preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
        preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
        now=_NOW + timedelta(seconds=1),
    )
    assert recovered.recovered is True
    recovered_store.complete_halted(
        lease=recovered,
        stage=AcceptedHandoffStage.DELEGATION,
        now=_NOW + timedelta(seconds=2),
    )
    assert len(_rows(path)) == 2


@pytest.mark.parametrize("unsafe_kind", ("symlink", "hardlink", "mode"))
def test_unsafe_existing_artifact_is_rejected(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    path = tmp_path / "accepted-handoff.jsonl"
    if unsafe_kind == "symlink":
        target = tmp_path / "target"
        target.write_text("x", encoding="utf-8")
        path.symlink_to(target)
    elif unsafe_kind == "hardlink":
        target = tmp_path / "target"
        target.write_text("x", encoding="utf-8")
        os.link(target, path)
    else:
        path.write_text("x", encoding="utf-8")
        path.chmod(0o644)

    with pytest.raises(
        AcceptedHandoffArtifactError,
        match="^accepted_handoff_artifact_unsafe$",
    ):
        FileAcceptedHandoffArtifactStore(path).reserve(
            preview_generation=_PREVIEW_GENERATION,
            preview_artifact_type=_PREVIEW_ARTIFACT_TYPE,
            preview_artifact_file_sha256=_PREVIEW_FILE_SHA256,
            preview_evidence_sha256=_PREVIEW_EVIDENCE_SHA256,
            now=_NOW,
        )
