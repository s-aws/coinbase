"""Offline crash-consistency tests for Slice 2R12 terminal persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from typing import Any, Callable

import pytest

import application.admin_api.futures_order_preview_r12 as r12_module
from application.admin_api.futures_order_preview import (
    canonical_json,
    canonical_sha256,
)
from application.admin_api.futures_order_preview_r12 import (
    FuturesPreviewR12ArtifactStore,
    FuturesPreviewR12AttemptWorkflow,
    FuturesPreviewR12EligibilityError,
    FuturesPreviewR12EligibilityStore,
    FuturesPreviewR12EligibilityWorkflow,
)
from application.admin_api.models import AdminFuturesOrderPreviewR12Response
from tests.unit.test_admin_api_futures_order_preview_r12 import (
    TEST_R12_PREDECESSOR_BINDING,
    _AttemptDelegate,
    _ReadyDelegate,
    _preview_response,
)


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _run_integrated(
    tmp_path: Path,
    *,
    response: object | None = None,
    attempt_now: Callable[[], datetime] | None = None,
) -> tuple[
    dict[str, Any],
    FuturesPreviewR12ArtifactStore,
    _AttemptDelegate,
]:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(
        artifact_path=attempt_path,
        response=response,
    )
    store = FuturesPreviewR12ArtifactStore(attempt_path)
    attempt = FuturesPreviewR12AttemptWorkflow(
        eligibility_store=FuturesPreviewR12EligibilityStore(
            eligibility_path
        ),
        store=store,
        predecessor_binding=TEST_R12_PREDECESSOR_BINDING,
        predecessor_validator=lambda: dict(TEST_R12_PREDECESSOR_BINDING),
        now=attempt_now or (lambda: NOW),
        correlation_id_factory=(
            lambda: "540e6dc8-b5d8-40c4-96b8-b3119805c70e"
        ),
        idempotency_key_factory=(
            lambda: "dbe48a6b-1cfe-4f63-abde-496c0544eef3"
        ),
    )
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=delegate,
        ),
        now=lambda: NOW,
        correlation_id_factory=(
            lambda: "033feded-a32c-45b5-9af0-3fb70c947917"
        ),
    )
    result = eligibility.run_cycle(attempt_workflow=attempt)
    return result, store, delegate


def _claim_and_terminal(
    tmp_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    terminal, store, _delegate = _run_integrated(tmp_path / "source")
    rows = store._read_rows()  # noqa: SLF001
    return deepcopy(dict(rows[0]["record"])), deepcopy(terminal)


def _claim_only_store(
    tmp_path: Path,
    claim: dict[str, Any],
) -> FuturesPreviewR12ArtifactStore:
    path = tmp_path / "attempt.jsonl"
    store = FuturesPreviewR12ArtifactStore(path)
    wrapped = store._record("claim", claim)  # noqa: SLF001
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(wrapped) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return store


def _recovery_workflow(
    *,
    eligibility_path: Path,
    store: FuturesPreviewR12ArtifactStore,
) -> FuturesPreviewR12AttemptWorkflow:
    return FuturesPreviewR12AttemptWorkflow(
        eligibility_store=FuturesPreviewR12EligibilityStore(
            eligibility_path
        ),
        store=store,
        predecessor_binding=TEST_R12_PREDECESSOR_BINDING,
        predecessor_validator=lambda: dict(TEST_R12_PREDECESSOR_BINDING),
        now=lambda: NOW,
        correlation_id_factory=lambda: "unused",
        idempotency_key_factory=lambda: "unused",
    )


@pytest.mark.parametrize(
    ("failure_stage", "claim_published"),
    [
        ("partial_write", False),
        ("claim_fsync", False),
        ("publish_link", False),
        ("publish_directory_fsync", True),
        ("temp_unlink", True),
        ("cleanup_directory_fsync", True),
    ],
)
def test_r12_atomic_claim_publish_fault_is_absent_or_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    claim_published: bool,
) -> None:
    source = tmp_path / "source"
    claim, _terminal = _claim_and_terminal(source)
    store = FuturesPreviewR12ArtifactStore(
        tmp_path / "target" / "attempt.jsonl"
    )

    if failure_stage == "partial_write":
        original = r12_module._write_all
        failed = False

        def fail_once(descriptor: int, payload: bytes) -> None:
            nonlocal failed
            if not failed:
                failed = True
                os.write(descriptor, payload[:17])
                raise OSError("synthetic partial claim write")
            original(descriptor, payload)

        monkeypatch.setattr(r12_module, "_write_all", fail_once)
    elif failure_stage == "claim_fsync":
        original = r12_module.os.fsync
        failed = False

        def fail_once(descriptor: int) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("synthetic claim fsync failure")
            original(descriptor)

        monkeypatch.setattr(r12_module.os, "fsync", fail_once)
    elif failure_stage == "publish_link":
        original = r12_module.os.link
        failed = False

        def fail_once(
            source_path: Path,
            destination_path: Path,
            *,
            follow_symlinks: bool = True,
        ) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("synthetic claim publish failure")
            original(
                source_path,
                destination_path,
                follow_symlinks=follow_symlinks,
            )

        monkeypatch.setattr(r12_module.os, "link", fail_once)
    elif failure_stage == "temp_unlink":
        original = r12_module.os.unlink
        failed = False

        def fail_once(path: Path) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("synthetic claim temp unlink failure")
            original(path)

        monkeypatch.setattr(r12_module.os, "unlink", fail_once)
    else:
        original = r12_module._fsync_directory
        calls = 0

        def fail_selected(path: Path) -> None:
            nonlocal calls
            calls += 1
            selected = (
                1 if failure_stage == "publish_directory_fsync" else 2
            )
            if calls == selected:
                raise OSError("synthetic claim directory fsync failure")
            original(path)

        monkeypatch.setattr(r12_module, "_fsync_directory", fail_selected)

    with pytest.raises(FuturesPreviewR12EligibilityError):
        store.reserve(claim)

    staging = list(
        store.path.parent.glob(f".{store.path.name}.claim-*")
    )
    if not claim_published:
        assert staging == []
        assert not store.path.exists()
        return

    expect_staging = failure_stage in {
        "publish_directory_fsync",
        "temp_unlink",
    }
    assert len(staging) == (1 if expect_staging else 0)
    rows = store._read_rows()  # noqa: SLF001
    assert len(rows) == 1
    assert rows[0]["record_type"] == "claim"
    assert rows[0]["record"] == claim
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.path.stat().st_nlink == (
        2 if expect_staging else 1
    )

    recovery = _recovery_workflow(
        eligibility_path=source / "source" / "eligibility.jsonl",
        store=store,
    )
    with recovery.eligibility_store.workflow_lease() as lease_nonce:
        terminal = recovery.recover_claim_only(_lease_nonce=lease_nonce)

    assert terminal is not None
    assert terminal["outcome"] == "unknown"
    assert terminal["blocker"] == "claim_only_recovery_unknown_consumed"
    assert not list(
        store.path.parent.glob(f".{store.path.name}.claim-*")
    )
    AdminFuturesOrderPreviewR12Response.model_validate(terminal)


def test_r12_claim_publish_durability_order_is_link_sync_unlink_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim, _terminal = _claim_and_terminal(tmp_path / "source")
    store = FuturesPreviewR12ArtifactStore(
        tmp_path / "target" / "attempt.jsonl"
    )
    events: list[str] = []
    original_link = r12_module.os.link
    original_unlink = r12_module.os.unlink
    original_directory_fsync = r12_module._fsync_directory

    def observed_link(
        source_path: Path,
        destination_path: Path,
        *,
        follow_symlinks: bool = True,
    ) -> None:
        events.append("link")
        original_link(
            source_path,
            destination_path,
            follow_symlinks=follow_symlinks,
        )

    def observed_unlink(path: Path) -> None:
        events.append("unlink")
        original_unlink(path)

    def observed_directory_fsync(path: Path) -> None:
        events.append("directory_fsync")
        original_directory_fsync(path)

    monkeypatch.setattr(r12_module.os, "link", observed_link)
    monkeypatch.setattr(r12_module.os, "unlink", observed_unlink)
    monkeypatch.setattr(
        r12_module,
        "_fsync_directory",
        observed_directory_fsync,
    )

    store.reserve(claim)

    assert events == [
        "link",
        "directory_fsync",
        "unlink",
        "directory_fsync",
    ]
    assert len(store._read_rows()) == 1  # noqa: SLF001
    assert store.path.stat().st_nlink == 1


def test_r12_recovery_removes_safe_orphan_staging_before_absence_return(
    tmp_path: Path,
) -> None:
    store = FuturesPreviewR12ArtifactStore(tmp_path / "attempt.jsonl")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    orphan = store.path.with_name(f".{store.path.name}.claim-orphan")
    orphan.write_bytes(b"unpublished-staging")
    orphan.chmod(0o600)
    recovery = _recovery_workflow(
        eligibility_path=tmp_path / "eligibility.jsonl",
        store=store,
    )

    with recovery.eligibility_store.workflow_lease() as lease_nonce:
        assert recovery.recover_claim_only(_lease_nonce=lease_nonce) is None

    assert not store.path.exists()
    assert not orphan.exists()


def test_r12_recovery_rejects_unsafe_orphan_staging_without_following(
    tmp_path: Path,
) -> None:
    store = FuturesPreviewR12ArtifactStore(tmp_path / "attempt.jsonl")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "unrelated"
    target.write_bytes(b"unrelated")
    target.chmod(0o600)
    orphan = store.path.with_name(f".{store.path.name}.claim-unsafe")
    orphan.symlink_to(target)
    recovery = _recovery_workflow(
        eligibility_path=tmp_path / "eligibility.jsonl",
        store=store,
    )

    with recovery.eligibility_store.workflow_lease() as lease_nonce:
        with pytest.raises(
            FuturesPreviewR12EligibilityError,
            match="staging state is invalid",
        ):
            recovery.recover_claim_only(_lease_nonce=lease_nonce)

    assert orphan.is_symlink()
    assert target.read_bytes() == b"unrelated"


def test_r12_recovery_removes_safe_terminal_staging_then_terminalizes_claim(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    claim, _terminal = _claim_and_terminal(source)
    store = _claim_only_store(tmp_path / "target", claim)
    orphan = store.path.with_name(
        f".{store.path.name}.terminal-orphan"
    )
    orphan.write_bytes(b"sanitized-unpublished-terminal-staging")
    orphan.chmod(0o400)
    recovery = _recovery_workflow(
        eligibility_path=source / "source" / "eligibility.jsonl",
        store=store,
    )

    with recovery.eligibility_store.workflow_lease() as lease_nonce:
        terminal = recovery.recover_claim_only(_lease_nonce=lease_nonce)

    assert terminal is not None
    assert terminal["outcome"] == "unknown"
    assert terminal["blocker"] == "claim_only_recovery_unknown_consumed"
    assert not orphan.exists()
    AdminFuturesOrderPreviewR12Response.model_validate(terminal)


def test_r12_strict_terminal_validation_precedes_any_temp_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim, terminal = _claim_and_terminal(tmp_path)
    store = _claim_only_store(tmp_path / "target", claim)
    invalid = deepcopy(terminal)
    invalid["status"] = "blocked"
    invalid["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in invalid.items()
            if key != "evidence_sha256"
        }
    )
    monkeypatch.setattr(
        r12_module.tempfile,
        "mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("temp file created before strict validation")
        ),
    )

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="terminal validation",
    ):
        store.append_validated_terminal(invalid)

    assert len(store._read_rows()) == 1  # noqa: SLF001
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "failure_stage",
    ["write", "fsync", "fchmod", "post_chmod_fsync", "replace"],
)
def test_r12_interrupted_terminal_build_leaves_clean_claim_then_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    claim, terminal = _claim_and_terminal(tmp_path)
    store = _claim_only_store(tmp_path / "target", claim)

    if failure_stage == "write":
        original = r12_module._write_all
        failed = False

        def fail_once(descriptor: int, payload: bytes) -> None:
            nonlocal failed
            if not failed:
                failed = True
                os.write(descriptor, payload[:17])
                raise OSError("synthetic partial terminal write")
            original(descriptor, payload)

        monkeypatch.setattr(r12_module, "_write_all", fail_once)
    elif failure_stage == "fsync":
        original = r12_module.os.fsync
        failed = False

        def fail_once(descriptor: int) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("synthetic terminal fsync failure")
            original(descriptor)

        monkeypatch.setattr(r12_module.os, "fsync", fail_once)
    elif failure_stage == "fchmod":
        original = r12_module.os.fchmod
        failed = False

        def fail_once(descriptor: int, mode: int) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("synthetic terminal chmod failure")
            original(descriptor, mode)

        monkeypatch.setattr(r12_module.os, "fchmod", fail_once)
    elif failure_stage == "post_chmod_fsync":
        original = r12_module.os.fsync
        calls = 0

        def fail_second(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic sealed-terminal fsync failure")
            original(descriptor)

        monkeypatch.setattr(r12_module.os, "fsync", fail_second)
    else:
        original = r12_module.os.replace
        failed = False

        def fail_once(source: Path, destination: Path) -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("synthetic terminal replace failure")
            original(source, destination)

        monkeypatch.setattr(r12_module.os, "replace", fail_once)

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="terminal persistence",
    ):
        store.append_validated_terminal(terminal)

    assert len(store._read_rows()) == 1  # noqa: SLF001
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert not list(store.path.parent.glob(f".{store.path.name}.terminal-*"))

    store.append_validated_terminal(terminal)

    assert store.read_completed() == terminal
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o400
    assert not list(store.path.parent.glob(f".{store.path.name}.terminal-*"))


def test_r12_parent_fsync_failure_after_replace_is_already_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim, terminal = _claim_and_terminal(tmp_path)
    store = _claim_only_store(tmp_path / "target", claim)
    monkeypatch.setattr(
        r12_module,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(
            OSError("synthetic parent fsync failure")
        ),
    )

    store.append_validated_terminal(terminal)

    assert store.read_completed() == terminal
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o400
    assert not list(store.path.parent.glob(f".{store.path.name}.terminal-*"))


def test_r12_post_claim_clock_failure_still_writes_strict_terminal(
    tmp_path: Path,
) -> None:
    attempt_path = tmp_path / "attempt.jsonl"

    def fail_after_claim() -> datetime:
        if attempt_path.exists():
            raise RuntimeError("private clock callback failure")
        return NOW

    with pytest.raises(FuturesPreviewR12EligibilityError, match="consumed"):
        _run_integrated(tmp_path, attempt_now=fail_after_claim)

    store = FuturesPreviewR12ArtifactStore(attempt_path)
    terminal = store.read_completed()
    assert terminal["outcome"] == "unknown"
    assert terminal["blocker"] == "eligibility_claim_marker_unknown_consumed"
    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(terminal).outcome
        == "unknown"
    )
    assert "private clock callback failure" not in attempt_path.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "preview_id",
    [None, "", " bad ", "bad\n", "x" * 257, 1],
)
def test_r12_invalid_raw_preview_id_is_strict_blocked_terminal(
    tmp_path: Path,
    preview_id: object,
) -> None:
    response = _preview_response()
    response["preview_id"] = preview_id

    with pytest.raises(FuturesPreviewR12EligibilityError, match="consumed"):
        _run_integrated(tmp_path, response=response)

    terminal = FuturesPreviewR12ArtifactStore(
        tmp_path / "attempt.jsonl"
    ).read_completed()
    assert terminal["outcome"] == "blocked"
    assert terminal["blocker"] == "post_preview_stage_blocked"
    assert terminal["post_preview_stage_evidence"]["stages"][0] == {
        "stage": "preview_response_validation",
        "status": "blocked",
        "reason_code": "futures_preview_response_validation_blocked",
    }
    AdminFuturesOrderPreviewR12Response.model_validate(terminal)


@pytest.mark.parametrize(
    ("mode", "downstream_preview_id"),
    [
        ("downstream_removed", None),
        ("raw_sentinel", "withheld"),
        ("downstream_whitespace", " bad "),
        ("downstream_nonprintable", "bad\n"),
        ("downstream_overlength", "x" * 257),
        ("downstream_non_string", 1),
    ],
)
def test_r12_preview_identifier_defensive_boundary_terminalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    downstream_preview_id: object,
) -> None:
    response = _preview_response()
    if mode == "raw_sentinel":
        response["preview_id"] = "withheld"
    else:
        original = r12_module.validate_preview_against_candidate

        def replace_identifier(
            preview: dict[str, Any],
            candidate: dict[str, Any],
        ) -> dict[str, Any]:
            normalized = original(preview, candidate)
            if mode == "downstream_removed":
                normalized.pop("preview_id", None)
            else:
                normalized["preview_id"] = downstream_preview_id
            return normalized

        monkeypatch.setattr(
            r12_module,
            "validate_preview_against_candidate",
            replace_identifier,
        )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="consumed"):
        _run_integrated(tmp_path, response=response)

    terminal = FuturesPreviewR12ArtifactStore(
        tmp_path / "attempt.jsonl"
    ).read_completed()
    assert terminal["outcome"] == "blocked"
    assert terminal["post_preview_stage_evidence"]["stages"][0] == {
        "stage": "preview_identifier_binding",
        "status": "blocked",
        "reason_code": "futures_preview_identifier_binding_blocked",
    }
    AdminFuturesOrderPreviewR12Response.model_validate(terminal)
