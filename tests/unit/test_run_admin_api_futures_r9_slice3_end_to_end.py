from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace

import pytest

from tools import run_admin_api_futures_r9_slice3_end_to_end as runner
from tools import run_admin_api_futures_r8_slice3_end_to_end as retired_r8


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _artifact_metadata(path: Path) -> tuple[int, ...] | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    return tuple(
        getattr(metadata, name)
        for name in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )


@pytest.fixture(autouse=True)
def _preserve_production_preview_artifacts():
    """Prove focused tests neither touch consumed R8 nor reserve fixed R9."""

    r8_path = runner.r9_tool.r8_tool.FUTURES_PREVIEW_R8_ARTIFACT_PATH
    r9_path = runner.FUTURES_PREVIEW_R9_ARTIFACT_PATH
    r8_before = _artifact_metadata(r8_path)
    r9_before = _artifact_metadata(r9_path)
    assert r8_before is not None
    assert r9_before is None
    yield
    assert _artifact_metadata(r8_path) == r8_before
    assert _artifact_metadata(r9_path) is None


def _terminal_envelope(
    status: str,
    *,
    plan_sha256: str = "1" * 64,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": (
            "slice3-terminal-roundtrip-evidence-v2"
            if status == "restored_baseline"
            else "slice3-halted-reconciliation-evidence-v1"
        ),
        "status": status,
        "plan_sha256": plan_sha256,
        "raw_response_included": False,
        "identifier_values_included": False,
    }
    if status == "halted":
        payload["exception_text_included"] = False
    payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def _write_authorization(path: Path, payload: bytes = b"authorized") -> str:
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _patch_clean_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, tuple[Path, ...]]:
    authorization = tmp_path / "authorization.txt"
    authorization_sha256 = _write_authorization(authorization)
    artifact_paths = tuple(
        tmp_path / name
        for name in (
            "r9.jsonl",
            "accepted-handoff.jsonl",
            "admission.json",
            "activation.json",
            "actions.jsonl",
            "reads.jsonl",
            "terminal.json",
        )
    )
    component = tmp_path / "component.py"
    component.write_bytes(b"component")
    openapi = tmp_path / "openapi.yaml"
    openapi.write_bytes(b"openapi")
    component_hash = hashlib.sha256(component.read_bytes()).hexdigest()
    openapi_hash = hashlib.sha256(openapi.read_bytes()).hexdigest()

    monkeypatch.setattr(runner, "OPERATOR_AUTHORIZATION_PATH", authorization)
    monkeypatch.setattr(
        runner,
        "OPERATOR_AUTHORIZATION_SHA256",
        authorization_sha256,
    )
    monkeypatch.setattr(runner, "OPENAPI_PATH", openapi)
    monkeypatch.setattr(
        runner,
        "FIXED_ATTEMPT_PATHS",
        artifact_paths,
    )
    # Every test that can reach store construction must redirect both the
    # aggregate tuple and the imported concrete R9 constant.  Patching only
    # the tuple previously allowed a synthetic failure-path test to reserve
    # the production R9 artifact before its mocked credential probe failed.
    monkeypatch.setattr(
        runner,
        "FUTURES_PREVIEW_R9_ARTIFACT_PATH",
        artifact_paths[0],
    )
    monkeypatch.setattr(
        runner,
        "ACCEPTED_HANDOFF_ARTIFACT_PATH",
        artifact_paths[1],
    )
    monkeypatch.setattr(
        runner,
        "AUDITED_COMPONENT_PATHS",
        MappingProxyType({"component": component}),
    )
    monkeypatch.setattr(
        runner,
        "AUDITED_COMPONENT_SHA256",
        MappingProxyType({"component": component_hash}),
    )
    monkeypatch.setattr(runner, "AUDITED_BACKEND_REVISION", "a" * 40)
    monkeypatch.setattr(runner, "AUDITED_OPENAPI_SHA256", openapi_hash)
    monkeypatch.setattr(runner, "AUDITED_RUNNER_LOGIC_SHA256", _SHA_A)
    monkeypatch.setattr(runner, "_current_runner_logic_sha256", lambda: _SHA_A)
    monkeypatch.setattr(
        runner,
        "_validate_audit_commit_transition",
        lambda _base: "b" * 40,
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "validate_production_predecessor",
        lambda: dict(runner.FUTURES_PREVIEW_R8_TERMINAL_BINDING),
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "_validate_fresh_claim_contract",
        lambda _path: None,
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "R8_PREVIEW_CALL_AUTHORITY_ACTIVE",
        False,
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "R9_PREVIEW_CALL_AUTHORITY_ACTIVE",
        False,
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "R9_FINAL_AUDIT_BINDING_READY",
        False,
    )
    monkeypatch.setattr(
        runner,
        "_validate_local_runtime_readiness",
        lambda: runner.EXPECTED_DEPENDENCY_BINDING_SHA256,
    )
    return authorization, artifact_paths


def _new_handoff_terminalizer(
    tmp_path: Path,
) -> runner.AcceptedHandoffTerminalizer:
    store = runner.FileAcceptedHandoffArtifactStore(
        tmp_path / "accepted-handoff.jsonl"
    )
    lease = store.reserve(
        preview_generation=9,
        preview_artifact_type=runner.FUTURES_PREVIEW_R9_ARTIFACT_TYPE,
        preview_artifact_file_sha256=_SHA_A,
        preview_evidence_sha256=_SHA_B,
        now=_NOW,
    )
    return runner.AcceptedHandoffTerminalizer(store=store, lease=lease)


def test_readiness_and_audit_constants_are_hard_fail_closed() -> None:
    assert runner.R9_SLICE3_END_TO_END_READY is False
    assert runner.AUDITED_BACKEND_REVISION is None
    assert runner.AUDITED_OPENAPI_SHA256 is None
    assert runner.AUDITED_RUNNER_LOGIC_SHA256 is None
    assert runner.AUDITED_COMPONENT_SHA256
    assert all(value is None for value in runner.AUDITED_COMPONENT_SHA256.values())
    assert runner.OPERATOR_AUTHORIZATION_SHA256 == (
        "5c9c2432179989446d79da2e8f173729103844a96f00e1eeec56dcf5c8e2dc51"
    )


def test_r8_end_to_end_entrypoint_is_a_permanent_no_io_tombstone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert retired_r8.R8_SLICE3_END_TO_END_READY is False
    assert retired_r8.main(["--confirm-one-r8-preview-and-slice3"]) == 2
    summary = json.loads(capsys.readouterr().err)
    assert summary == {
        "artifact_created": False,
        "blocker": "futures_r8_slice3_permanently_retired",
        "coinbase_client_constructed": False,
        "coinbase_read_ran": False,
        "preview_order_attempt_count": 0,
        "slice3_exchange_mutation_attempt_count": 0,
        "status": "blocked",
        "workflow_ready": False,
    }


def test_stage0_dormant_source_requires_no_live_evidence() -> None:
    assert runner._SOURCE_DECLARED_READY is False
    assert runner._STAGE0_EVIDENCE is None


def test_r9_plan_adapter_checks_documented_expiry_before_legacy_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "_build_slice3_admitted_plan_from_r8",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy binding reached without documented expiry")
        ),
    )
    with pytest.raises(
        ValueError,
        match="^slice3_handoff_preview_expiry_unavailable$",
    ):
        runner.build_slice3_admitted_plan_from_r9(
            ephemeral_evidence={
                "completed_at": _NOW.isoformat(),
                "preview_response": {},
            },
            persisted_terminal={},
            accepted_r9_binding=object(),
            account_binding=object(),
            authorization_sha256=_SHA_A,
            now=_NOW,
            backend_revision="a" * 40,
            openapi_revision=_SHA_B,
        )


def test_operator_diagnosis_discloses_r9_expiry_halt_and_opaque_freshness_limit() -> None:
    diagnosis = Path("docs/FUTURES_SLICE_2R8_TERMINAL_DIAGNOSIS.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(diagnosis.split())

    assert "no documented Preview expiry field or TTL" in normalized
    assert "halts at the `PLAN` boundary" in normalized
    assert (
        "zero admission, activation, port construction, or exchange mutation"
        in normalized
    )
    assert "cannot activate Slice 3" in normalized
    assert "R8 identifier hashes remain intentionally unavailable" in normalized


def test_r9_predecessor_binding_is_exact_opaque_r8_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = dict(runner.FUTURES_PREVIEW_R8_TERMINAL_BINDING)
    monkeypatch.setattr(
        runner.r9_tool,
        "validate_production_predecessor",
        lambda: observed,
    )
    runner._validate_immutable_predecessors()

    monkeypatch.setattr(
        runner.r9_tool,
        "validate_production_predecessor",
        lambda: {**observed, "file_sha256": _SHA_A},
    )
    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_predecessor_binding_invalid$",
    ):
        runner._validate_immutable_predecessors()


def test_r9_composition_uses_only_the_r9_producer_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deferred = object()
    store = object()
    producer = object()
    calls: list[dict[str, object]] = []

    def build_r9_producer(**kwargs):
        calls.append(dict(kwargs))
        return producer

    monkeypatch.setattr(runner.r9_tool, "build_r9_producer", build_r9_producer)
    assert runner._build_r9_producer(
        deferred_session=deferred,
        store=store,
    ) is producer
    assert calls == [{"rest_client": deferred, "store": store}]


def test_stage0_dependency_record_binding_matches_exact_installation() -> None:
    assert runner._stage0_validate_installed_dependencies() == (
        runner.EXPECTED_DEPENDENCY_BINDING_SHA256
    )


def test_all_git_probes_use_fixed_binary_arguments_and_closed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        stdout: str | bytes = "value\n" if kwargs.get("text") else b"runner\n"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner._stage0_git_text("rev-parse", "HEAD") == "value"
    assert runner._stage0_runner_at_revision("a" * 40) == b"runner\n"
    assert runner._git_text("rev-parse", "HEAD") == "value"
    assert runner._runner_bytes_at_revision("a" * 40) == b"runner\n"

    expected_prefix = [
        "/usr/bin/git",
        "--no-optional-locks",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
    ]
    expected_environment = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": "/nonexistent",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    assert len(calls) == 4
    for args, kwargs in calls:
        assert args[: len(expected_prefix)] == expected_prefix
        assert kwargs["env"] == expected_environment
        assert kwargs["cwd"] == runner.REPO_ROOT


def test_stage0_import_guard_rejects_unverified_site_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests_spec = runner.importlib.machinery.PathFinder.find_spec("requests")
    assert requests_spec is not None
    assert requests_spec.origin is not None
    monkeypatch.setattr(
        runner,
        "_STAGE0_VERIFIED_DEPENDENCY_FILES",
        {str(Path(requests_spec.origin).absolute())},
    )

    assert runner._Stage0VerifiedDependencyFinder.find_spec("requests") is not None
    with pytest.raises(
        ImportError,
        match="^futures_r9_slice3_unverified_dependency_import_blocked$",
    ):
        runner._Stage0VerifiedDependencyFinder.find_spec("pytest")


def test_ready_cli_without_isolated_python_blocks_before_project_import(
    tmp_path: Path,
) -> None:
    copied_runner = tmp_path / "ready-runner.py"
    source = runner.RUNNER_PATH.read_text(encoding="utf-8").replace(
        "R9_SLICE3_END_TO_END_READY = False",
        "R9_SLICE3_END_TO_END_READY = True",
        1,
    )
    copied_runner.write_text(source, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(copied_runner), "--preflight"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    rendered = completed.stdout + completed.stderr
    assert completed.returncode == 2
    assert "futures_r9_slice3_stage0_isolation_required" in rendered
    assert "Traceback" not in rendered
    assert "ModuleNotFoundError" not in rendered


def test_ready_isolated_cli_rejects_untracked_before_project_import(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    tools = repo / "tools"
    tools.mkdir(parents=True)
    copied_runner = tools / runner.RUNNER_PATH.name
    pycache_prefix = tmp_path / "empty-pycache"
    pycache_prefix.mkdir(mode=0o700)
    source = runner.RUNNER_PATH.read_text(encoding="utf-8")
    source = source.replace(
        'Path("/home/developer/coinbase/coinbase")',
        f'Path("{repo}")',
        1,
    ).replace(
        'Path("/tmp/coinbase-r9-slice3-empty-pycache")',
        f'Path("{pycache_prefix}")',
        1,
    ).replace(
        "R9_SLICE3_END_TO_END_READY = False",
        "R9_SLICE3_END_TO_END_READY = True",
        1,
    )
    copied_runner.write_text(source, encoding="utf-8")
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "tools/run_admin_api_futures_r9_slice3_end_to_end.py"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Stage0 Test",
            "-c",
            "user.email=stage0@example.invalid",
            "commit",
            "-m",
            "base",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "untracked-project-module.py").write_text(
        "raise RuntimeError('must not import')\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            runner._STAGE0_PYTHON,
            "-I",
            "-S",
            "-B",
            "-X",
            f"pycache_prefix={pycache_prefix}",
            str(copied_runner),
            "--preflight",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    rendered = completed.stdout + completed.stderr
    assert completed.returncode == 2
    assert "futures_r9_slice3_stage0_worktree_not_clean" in rendered
    assert "Traceback" not in rendered
    assert "ModuleNotFoundError" not in rendered
    assert list(pycache_prefix.iterdir()) == []


def _runner_source(binding: bytes, suffix: bytes = b"logic\n") -> bytes:
    ready = b"True" if b"True" in binding else b"False"
    components = b"".join(
        b'        "' + name.encode() + b'": None,\n'
        for name in runner.AUDITED_COMPONENT_PATHS
    )
    audit_block = (
        b"R9_SLICE3_END_TO_END_READY = "
        + ready
        + b"\nAUDITED_BACKEND_REVISION: str | None = None\n"
        + b"AUDITED_OPENAPI_SHA256: str | None = None\n"
        + b"AUDITED_COMPONENT_SHA256: Mapping[str, str | None] = "
        + b"MappingProxyType(\n    {\n"
        + components
        + b"    }\n)\n"
        + b"AUDITED_RUNNER_LOGIC_SHA256: str | None = None\n"
    )
    return (
        b"prefix\n# AUDIT_BINDINGS_BEGIN\n"
        + audit_block
        + b"# AUDIT_BINDINGS_END\n"
        + suffix
    )


def test_runner_logic_normalization_excludes_only_binding_block() -> None:
    left = runner._normalize_runner_logic(_runner_source(b"READY = False"))
    right = runner._normalize_runner_logic(_runner_source(b"READY = True"))
    changed_logic = runner._normalize_runner_logic(
        _runner_source(b"READY = True", suffix=b"changed\n")
    )

    assert left == right
    assert left != changed_logic


def test_runner_logic_normalization_rejects_executable_binding_statement() -> None:
    source = _runner_source(b"READY = False")
    source = source.replace(
        b"# AUDIT_BINDINGS_END\n",
        b"raise RuntimeError('must never execute')\n# AUDIT_BINDINGS_END\n",
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_runner_binding_invalid$",
    ):
        runner._normalize_runner_logic(source)


def test_current_runner_bytes_rejects_alternate_module_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "__file__", str(tmp_path / "runner-link.py"))
    monkeypatch.setattr(
        runner,
        "_read_regular_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("alternate runner path read")
        ),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_runner_binding_invalid$",
    ):
        runner._current_runner_bytes()


def _patch_valid_audit_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str, dict[tuple[str, ...], str]]:
    base = "a" * 40
    current = "b" * 40
    outputs = {
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("symbolic-ref", "--short", "HEAD"): "main",
        ("rev-parse", "refs/remotes/origin/main"): current,
        ("rev-list", "--parents", "-n", "1", current): f"{current} {base}",
        ("rev-list", "--count", f"{base}..{current}"): "1",
        (
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            f"{base}..{current}",
            "--",
        ): "tools/run_admin_api_futures_r9_slice3_end_to_end.py",
    }
    monkeypatch.setattr(runner, "_current_backend_revision", lambda: current)
    monkeypatch.setattr(runner, "_git_text", lambda *args: outputs[args])
    monkeypatch.setattr(
        runner,
        "_runner_bytes_at_revision",
        lambda _revision: _runner_source(b"READY = False"),
    )
    monkeypatch.setattr(
        runner,
        "_current_runner_bytes",
        lambda: _runner_source(b"READY = True"),
    )
    return base, current, outputs


def test_audit_transition_requires_exact_constants_only_child_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, current, _outputs = _patch_valid_audit_transition(monkeypatch)

    assert runner._validate_audit_commit_transition(base) == current


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("dirty", "futures_r9_slice3_tracked_worktree_not_clean"),
        ("branch", "futures_r9_slice3_branch_not_main"),
        ("origin", "futures_r9_slice3_origin_main_not_synchronized"),
        ("parent", "futures_r9_slice3_audit_commit_transition_invalid"),
        ("scope", "futures_r9_slice3_audit_commit_scope_invalid"),
        ("logic", "futures_r9_slice3_audit_commit_logic_changed"),
    ],
)
def test_audit_transition_rejects_drift_outside_binding_block(
    mutation: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, current, outputs = _patch_valid_audit_transition(monkeypatch)
    if mutation == "dirty":
        outputs[("status", "--porcelain", "--untracked-files=all")] = "?? file.py"
    elif mutation == "branch":
        outputs[("symbolic-ref", "--short", "HEAD")] = "codex/unsafe"
    elif mutation == "origin":
        outputs[("rev-parse", "refs/remotes/origin/main")] = "c" * 40
    elif mutation == "parent":
        outputs[("rev-list", "--parents", "-n", "1", current)] = f"{current} {'c' * 40}"
    elif mutation == "scope":
        outputs[
            (
                "diff",
                "--name-only",
                "--diff-filter=ACDMRTUXB",
                f"{base}..{current}",
                "--",
            )
        ] += "\napplication/admin_api/unsafe.py"
    else:
        monkeypatch.setattr(
            runner,
            "_current_runner_bytes",
            lambda: _runner_source(b"READY = True", suffix=b"changed\n"),
        )

    with pytest.raises(runner.R9Slice3RunnerError, match=f"^{reason}$"):
        runner._validate_audit_commit_transition(base)


def test_preflight_validates_every_binding_without_client_or_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization, artifact_paths = _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(
        runner,
        "build_deferred_r9_session",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("client constructed")),
    )

    before = {path: path.exists() for path in (authorization, *artifact_paths)}
    assert runner.main(["--preflight"]) == 0
    after = {path: path.exists() for path in (authorization, *artifact_paths)}

    assert before == after
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "artifact_created": False,
        "blocker": None,
        "coinbase_client_constructed": False,
        "coinbase_read_ran": False,
        "dependency_binding_sha256": (
            runner.EXPECTED_DEPENDENCY_BINDING_SHA256
        ),
        "preview_order_attempt_count": 0,
        "slice3_exchange_mutation_attempt_count": 0,
        "status": "ready",
        "workflow_ready": True,
    }


def test_preflight_still_checks_audit_placeholders_while_gate_is_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "AUDITED_BACKEND_REVISION", None)
    monkeypatch.setattr(
        runner,
        "build_deferred_r9_session",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("client constructed")),
    )

    assert runner.main(["--preflight"]) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "blocked"
    assert summary["blocker"] == "futures_r9_slice3_audit_binding_incomplete"
    assert summary["workflow_ready"] is False


def test_preflight_rejects_runner_logic_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(runner, "_current_runner_logic_sha256", lambda: _SHA_B)

    assert runner.main(["--preflight"]) == 2
    assert json.loads(capsys.readouterr().out)["blocker"] == (
        "futures_r9_slice3_audited_runner_changed"
    )


def test_preflight_requires_runtime_enforced_admission_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(runner, "_runtime_enforces_admission_binding", lambda: False)

    assert runner.main(["--preflight"]) == 2
    assert json.loads(capsys.readouterr().out)["blocker"] == (
        "futures_r9_slice3_runtime_admission_binding_unavailable"
    )


def test_preflight_rejects_authorization_byte_change_without_leaking_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorization, _paths = _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    authorization.write_bytes(b"PRIVATE CHANGED AUTHORIZATION TEXT")

    assert runner.main(["--preflight"]) == 2
    rendered = capsys.readouterr().out
    assert "PRIVATE CHANGED" not in rendered
    assert json.loads(rendered)["blocker"] == (
        "futures_r9_slice3_authorization_binding_invalid"
    )


def test_preflight_rejects_local_credential_blocker_before_claim_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(
        runner,
        "_validate_local_runtime_readiness",
        lambda: (_ for _ in ()).throw(
            runner.R9Slice3RunnerError(
                "futures_r9_slice3_credential_provider_absent"
            )
        ),
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "_validate_fresh_claim_contract",
        lambda _path: (_ for _ in ()).throw(AssertionError("claim checked")),
    )

    assert runner.main(["--preflight"]) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["blocker"] == "futures_r9_slice3_credential_provider_absent"
    assert summary["artifact_created"] is False


def test_stage0_credential_provider_requires_fixed_file_and_no_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tls_overrides = {
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "SSLKEYLOGFILE",
        "OPENSSL_CONF",
        "OPENSSL_MODULES",
        "NETRC",
        "BOTO_CONFIG",
    }
    for name in tuple(os.environ):
        upper = name.upper()
        if upper.startswith("AWS_") or upper.endswith("_PROXY") or (
            upper in tls_overrides
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        runner,
        "_stage0_secure_credential_file_present",
        lambda _path: True,
    )
    runner._stage0_validate_credential_provider_presence()

    monkeypatch.setenv("AWS_PROFILE", "default")
    with pytest.raises(
        runner._Stage0Error,
        match="^futures_r9_slice3_credential_provider_override_present$",
    ):
        runner._stage0_validate_credential_provider_presence()

    monkeypatch.delenv("AWS_PROFILE")
    for name in (
        "https_proxy",
        "REQUESTS_CA_BUNDLE",
        "SSLKEYLOGFILE",
        "OPENSSL_CONF",
        "NETRC",
    ):
        monkeypatch.setenv(name, "/private/inherited-override")
        with pytest.raises(
            runner._Stage0Error,
            match="^futures_r9_slice3_credential_provider_override_present$",
        ):
            runner._stage0_validate_credential_provider_presence()
        monkeypatch.delenv(name)
    monkeypatch.setattr(
        runner,
        "_stage0_secure_credential_file_present",
        lambda _path: False,
    )
    with pytest.raises(
        runner._Stage0Error,
        match="^futures_r9_slice3_credential_provider_absent$",
    ):
        runner._stage0_validate_credential_provider_presence()


def test_fixed_r9_secret_lookup_uses_only_the_pinned_bounded_aws_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    secret_payload = '{"SecretString":"PRIVATE_EPHEMERAL_SECRET"}'

    def fake_run(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=secret_payload,
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner._lookup_fixed_r9_secret("coinbase", "us-east-1") == (
        secret_payload
    )
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == [
        str(runner._AWS_CLI_CANONICAL_PATH),
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        "coinbase",
        "--region",
        "us-east-1",
        "--endpoint-url",
        "https://secretsmanager.us-east-1.amazonaws.com",
        "--ca-bundle",
        str(runner._AWS_CLI_CA_BUNDLE),
        "--output",
        "json",
        "--no-cli-pager",
        "--cli-connect-timeout",
        "10",
        "--cli-read-timeout",
        "20",
    ]
    assert kwargs == {
        "capture_output": True,
        "check": False,
        "cwd": runner.REPO_ROOT,
        "env": {
            "AWS_CLI_AUTO_PROMPT": "off",
            "AWS_CLI_HISTORY_FILE": "/dev/null",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_PAGER": "",
            "AWS_PROFILE": "default",
            "AWS_REGION": "us-east-1",
            "AWS_RETRY_MODE": "standard",
            "AWS_SHARED_CREDENTIALS_FILE": "/home/developer/.aws/credentials",
            "HOME": "/nonexistent",
            "LC_ALL": "C",
            "PATH": str(runner._AWS_CLI_CANONICAL_PATH.parent),
        },
        "stdin": subprocess.DEVNULL,
        "text": True,
        "timeout": 35,
    }


@pytest.mark.parametrize(
    ("secret_id", "region"),
    [("other", "us-east-1"), ("coinbase", "us-west-2"), ("coinbase", None)],
)
def test_fixed_r9_secret_lookup_rejects_credential_scope_drift(
    secret_id: str,
    region: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("AWS CLI invoked")
        ),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_credential_preparation_failed$",
    ):
        runner._lookup_fixed_r9_secret(secret_id, region)


def test_fixed_r9_secret_lookup_withholds_cli_failure_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="PRIVATE AWS FAILURE CONTEXT",
        ),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_credential_preparation_failed$",
    ) as captured:
        runner._lookup_fixed_r9_secret("coinbase", "us-east-1")
    assert "PRIVATE" not in str(captured.value)


def test_confirmed_credential_preparation_failure_leaves_every_path_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _authorization, paths = _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    construction_calls = 0

    def fail_construction(*, run_secret_lookup):
        nonlocal construction_calls
        construction_calls += 1
        assert run_secret_lookup is runner._lookup_fixed_r9_secret
        raise RuntimeError("PRIVATE SDK CONSTRUCTION FAILURE")

    monkeypatch.setattr(
        runner.r9_tool,
        "_build_r9_canonical_preview_session",
        fail_construction,
    )
    monkeypatch.setattr(
        runner,
        "build_deferred_r9_session",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("deferred session constructed")
        ),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_credential_preparation_failed$",
    ):
        runner.execute_confirmed_workflow(
            authorization_bytes=runner.OPERATOR_AUTHORIZATION_PATH.read_bytes(),
        )

    assert construction_calls == 1
    assert all(not path.exists() and not path.is_symlink() for path in paths)


def test_malformed_coinbase_key_fails_local_probe_before_claim_or_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import requests

    production_path = (
        runner.FUTURES_PREVIEW_R9_ARTIFACT_PATH
    )
    production_metadata = (
        tuple(
            getattr(production_path.lstat(), name)
            for name in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        )
        if production_path.exists()
        else None
    )
    _authorization, paths = _patch_clean_preflight(monkeypatch, tmp_path)
    assert runner.FUTURES_PREVIEW_R9_ARTIFACT_PATH == paths[0]
    assert runner._build_r9_store().path == paths[0]
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(
        runner,
        "_lookup_fixed_r9_secret",
        lambda secret_id, region: json.dumps(
            {
                "SecretString": json.dumps(
                    {
                        "api_key": "organizations/test/apiKeys/key",
                        "api_secret": "not-a-valid-ec-private-key",
                    }
                )
            }
        ),
    )
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("credential probe attempted network access")
        ),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_credential_preparation_failed$",
    ):
        runner.execute_confirmed_workflow(
            authorization_bytes=runner.OPERATOR_AUTHORIZATION_PATH.read_bytes(),
        )

    assert all(not path.exists() and not path.is_symlink() for path in paths)
    current_production_metadata = (
        tuple(
            getattr(production_path.lstat(), name)
            for name in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        )
        if production_path.exists()
        else None
    )
    assert current_production_metadata == production_metadata


@pytest.mark.parametrize(
    "drifted_constant",
    [
        "R8_PREVIEW_CALL_AUTHORITY_ACTIVE",
        "R9_PREVIEW_CALL_AUTHORITY_ACTIVE",
        "R9_FINAL_AUDIT_BINDING_READY",
    ],
)
def test_preflight_rejects_every_parallel_preview_entrypoint(
    drifted_constant: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(runner.r9_tool, drifted_constant, True)

    assert runner.main(["--preflight"]) == 2
    assert json.loads(capsys.readouterr().out)["blocker"] == (
        "futures_r9_slice3_parallel_preview_path_enabled"
    )


@pytest.mark.parametrize("path_index", range(7))
def test_preflight_rejects_every_consumed_fixed_path(
    path_index: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _authorization, paths = _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    paths[path_index].write_bytes(b"occupied")

    assert runner.main(["--preflight"]) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["blocker"] == "futures_r9_slice3_attempt_path_not_fresh"


def test_confirmation_gate_blocks_before_preflight_or_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", False)
    monkeypatch.setattr(
        runner,
        "validate_production_preflight",
        lambda: (_ for _ in ()).throw(AssertionError("preflight ran")),
    )
    monkeypatch.setattr(
        runner,
        "build_deferred_r9_session",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("client constructed")),
    )

    assert runner.main(["--confirm-one-r9-preview-and-slice3"]) == 2
    summary = json.loads(capsys.readouterr().err)
    assert summary["blocker"] == "futures_r9_slice3_workflow_not_ready"
    assert summary["coinbase_client_constructed"] is False


def test_callable_execution_runs_preflight_before_store_or_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(
        runner,
        "validate_production_preflight",
        lambda: (_ for _ in ()).throw(
            runner.R9Slice3RunnerError("futures_r9_slice3_audit_binding_incomplete")
        ),
    )
    monkeypatch.setattr(
        runner,
        "_build_r9_store",
        lambda: (_ for _ in ()).throw(AssertionError("store constructed")),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_audit_binding_incomplete$",
    ):
        runner.execute_confirmed_workflow(authorization_bytes=b"authorized")


def test_callable_execution_rejects_wrong_authorization_before_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(
        runner,
        "validate_production_preflight",
        lambda: runner.PreflightEvidence(
            authorization_bytes=b"authorized",
            backend_revision="b" * 40,
            openapi_sha256=_SHA_A,
        ),
    )
    monkeypatch.setattr(
        runner,
        "_build_r9_store",
        lambda: (_ for _ in ()).throw(AssertionError("store constructed")),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_authorization_binding_invalid$",
    ):
        runner.execute_confirmed_workflow(authorization_bytes=b"wrong")


@pytest.mark.parametrize("phase", ["preflight", "execution"])
def test_cli_sanitizes_unexpected_exception_without_traceback(
    phase: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    private_text = "PRIVATE_RAW_RESPONSE_AND_IDENTIFIER"
    if phase == "preflight":
        monkeypatch.setattr(
            runner,
            "validate_production_preflight",
            lambda: (_ for _ in ()).throw(RuntimeError(private_text)),
        )
        argv = ["--preflight"]
    else:
        monkeypatch.setattr(
            runner,
            "validate_production_preflight",
            lambda: runner.PreflightEvidence(
                authorization_bytes=b"authorized",
                backend_revision="b" * 40,
                openapi_sha256=_SHA_A,
            ),
        )
        monkeypatch.setattr(
            runner,
            "execute_confirmed_workflow",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(private_text)),
        )
        argv = ["--confirm-one-r9-preview-and-slice3"]

    assert runner.main(argv) == 2
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert private_text not in rendered
    assert "Traceback" not in rendered
    summary = json.loads(captured.out or captured.err)
    assert summary["blocker"] == "futures_r9_slice3_validation_blocked"


def test_production_composition_fails_closed_without_runtime_admission_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(
        runner,
        "_runtime_enforces_admission_binding",
        lambda: False,
    )
    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_runtime_admission_binding_unavailable$",
    ):
        runner.run_accepted_slice3_handoff(
            ephemeral_evidence={},
            persisted_terminal={},
            accepted_session=SimpleNamespace(),
            deferred_session=SimpleNamespace(),
            r9_store=SimpleNamespace(),
            callback_capability=object(),
            authorization_bytes=b"authorized",
            r9_artifact_file_sha256=_SHA_A,
            now=_NOW,
            handoff_terminalizer=_new_handoff_terminalizer(tmp_path),
        )


def test_accepted_handoff_rejects_unowned_session_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(runner, "_runtime_enforces_admission_binding", lambda: True)
    monkeypatch.setattr(
        runner,
        "_validate_audited_state",
        lambda: ("b" * 40, _SHA_A),
    )
    monkeypatch.setattr(
        runner,
        "OPERATOR_AUTHORIZATION_SHA256",
        hashlib.sha256(b"authorized").hexdigest(),
    )
    monkeypatch.setattr(
        runner,
        "_consume_accepted_handoff_capability",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_same_session_handoff_invalid$",
    ):
        runner.run_accepted_slice3_handoff(
            ephemeral_evidence={"status": "accepted"},
            persisted_terminal={"status": "accepted", "outcome": "accepted"},
            accepted_session=SimpleNamespace(
                delegate=object(),
                account_binding=object(),
            ),
            deferred_session=SimpleNamespace(),
            r9_store=SimpleNamespace(),
            callback_capability=object(),
            authorization_bytes=b"authorized",
            r9_artifact_file_sha256=_SHA_A,
            now=_NOW,
            handoff_terminalizer=_new_handoff_terminalizer(tmp_path),
        )


def test_accepted_handoff_capability_is_identity_bound_and_one_use() -> None:
    deferred = object()
    accepted = object()
    store = object()
    persisted = object()
    capability = runner._ACCEPTED_HANDOFF_CAPABILITIES.issue(
        deferred_session=deferred,
        accepted_session=accepted,
        r9_store=store,
        persisted_terminal=persisted,
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_same_session_handoff_invalid$",
    ):
        runner._consume_accepted_handoff_capability(
            capability,
            deferred_session=deferred,
            accepted_session=object(),
            r9_store=store,
            persisted_terminal=persisted,
        )

    replacement = runner._ACCEPTED_HANDOFF_CAPABILITIES.issue(
        deferred_session=deferred,
        accepted_session=accepted,
        r9_store=store,
        persisted_terminal=persisted,
    )
    runner._consume_accepted_handoff_capability(
        replacement,
        deferred_session=deferred,
        accepted_session=accepted,
        r9_store=store,
        persisted_terminal=persisted,
    )
    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_same_session_handoff_invalid$",
    ):
        runner._consume_accepted_handoff_capability(
            replacement,
            deferred_session=deferred,
            accepted_session=accepted,
            r9_store=store,
            persisted_terminal=persisted,
        )


def test_same_process_continuation_reenters_once_after_consumed_create_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    expected = object()

    class Orchestrator:
        def run(self, **_kwargs):
            calls.append("run")
            if len(calls) == 1:
                raise KeyboardInterrupt
            return expected

    monkeypatch.setattr(
        runner,
        "_create_boundary_is_consumed",
        lambda **_kwargs: True,
    )

    result = runner._run_with_same_process_risk_off_continuation(
        orchestrator=Orchestrator(),
        action_store=object(),
        plan=object(),
        activation_store=object(),
        expected_activation_manifest_sha256=_SHA_A,
    )

    assert result is expected
    assert calls == ["run", "run"]


def test_same_process_continuation_never_reenters_before_create_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Orchestrator:
        def run(self, **_kwargs):
            calls.append("run")
            raise KeyboardInterrupt

    monkeypatch.setattr(
        runner,
        "_create_boundary_is_consumed",
        lambda **_kwargs: False,
    )

    with pytest.raises(KeyboardInterrupt):
        runner._run_with_same_process_risk_off_continuation(
            orchestrator=Orchestrator(),
            action_store=object(),
            plan=object(),
            activation_store=object(),
            expected_activation_manifest_sha256=_SHA_A,
        )

    assert calls == ["run"]


def test_accepted_handoff_seals_admission_then_activation_and_runs_one_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    delegate = object()
    account_binding = SimpleNamespace(
        adapter_evidence_sha256="c" * 64,
        permission_evidence_sha256="d" * 64,
        portfolio_catalog_sha256="e" * 64,
    )
    accepted_session = SimpleNamespace(
        delegate=delegate,
        account_binding=account_binding,
    )
    accepted_r9_binding = object()
    authority_bundle = object()
    plan = SimpleNamespace(
        plan_sha256="1" * 64,
        expires_at=_NOW + timedelta(minutes=5),
        risk_off_expires_at=_NOW + timedelta(minutes=15),
        backend_revision="b" * 40,
        openapi_revision="2" * 64,
        portfolio=SimpleNamespace(
            sanitized_evidence=lambda: {"portfolio_id_sha256": "3" * 64},
            permission_evidence_sha256="d" * 64,
            portfolio_catalog_sha256="e" * 64,
        ),
        create=SimpleNamespace(
            client_order_id="private-create-id",
            preview_id="private-preview-id",
            limit_price="9.5",
        ),
        close_client_order_id="private-close-id",
        preview=SimpleNamespace(
            candidate_contract_size="10",
            accepted_at=_NOW,
        ),
    )
    admission_chain = SimpleNamespace(chain_sha256="4" * 64)
    admission_seal = SimpleNamespace(
        chain=admission_chain,
        chain_sha256="4" * 64,
        record_sha256="5" * 64,
        artifact_file_sha256="6" * 64,
    )
    activation_manifest = SimpleNamespace(manifest_sha256="7" * 64)
    activation_seal = SimpleNamespace(manifest_sha256="7" * 64)
    expected_result = SimpleNamespace(
        status=SimpleNamespace(value="restored_baseline"),
        reason_code="restored_baseline",
        terminal_artifact_sha256="8" * 64,
    )

    class R9BindingFactory:
        @classmethod
        def from_accepted_evidence(cls, **kwargs):
            assert kwargs == {
                "artifact_file_sha256": _SHA_A,
                "evidence": {"persisted": True},
            }
            events.append("r9_binding")
            return accepted_r9_binding

    def admitted_plan_builder(**kwargs):
        assert kwargs["accepted_r9_binding"] is accepted_r9_binding
        assert kwargs["account_binding"] is account_binding
        assert kwargs["authorization_sha256"] == (runner.OPERATOR_AUTHORIZATION_SHA256)
        assert kwargs["backend_revision"] == "b" * 40
        assert kwargs["openapi_revision"] == "2" * 64
        events.append("plan")
        return plan, authority_bundle

    def admission_builder(**kwargs):
        assert kwargs["plan"] is plan
        assert kwargs["authority_bundle"] is authority_bundle
        assert kwargs["expires_at"] == plan.risk_off_expires_at
        events.append("admission_chain")
        return admission_chain

    class AdmissionStore:
        def seal(self, chain, *, now):
            assert chain is admission_chain
            assert now == _NOW
            events.append("admission_seal")
            return admission_seal

    admission_store = AdmissionStore()

    def activation_builder(**kwargs):
        assert kwargs["plan"] is plan
        assert kwargs["admission_seal"] is admission_seal
        assert kwargs["authorization_text"] == b"authorized"
        events.append("activation_manifest")
        return activation_manifest

    class ActivationStore:
        def seal(self, manifest, *, now):
            assert manifest is activation_manifest
            assert now == _NOW
            events.append("activation_seal")
            return activation_seal

    activation_store = ActivationStore()
    action_store = object()
    read_journal = object()
    terminal_store = object()
    ports: list[object] = []

    class Port:
        def __init__(self, received_delegate, **kwargs):
            assert received_delegate is delegate
            assert kwargs["account_binding"] is account_binding
            assert kwargs["expected_adapter_evidence_sha256"] == "c" * 64
            assert kwargs["expected_portfolio_id_sha256"] == "3" * 64
            assert kwargs["order_lookup_start_at"] == plan.preview.accepted_at
            assert kwargs["order_lookup_end_at"] == plan.risk_off_expires_at
            events.append("port")
            ports.append(self)

    class Orchestrator:
        def __init__(self, **kwargs):
            assert kwargs["action_store"] is action_store
            assert kwargs["read_journal"] is read_journal
            assert kwargs["terminal_store"] is terminal_store
            assert kwargs["admission_store"] is admission_store
            self.port_factory = kwargs["port_factory"]
            events.append("orchestrator")

        def run(self, **kwargs):
            assert kwargs["plan"] is plan
            assert kwargs["activation_store"] is activation_store
            assert kwargs["expected_activation_manifest_sha256"] == "7" * 64
            first_port = self.port_factory(activation_seal)
            assert first_port is ports[0]
            assert self.port_factory(activation_seal) is first_port
            events.append("run")
            return expected_result

    monkeypatch.setattr(runner, "_runtime_enforces_admission_binding", lambda: True)
    monkeypatch.setattr(
        runner,
        "_validate_accepted_handoff_provenance",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        runner,
        "_consume_accepted_handoff_capability",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(
        runner,
        "_validate_r9_documented_preview_expiry_boundary",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(runner, "Slice3AcceptedR9Binding", R9BindingFactory)
    monkeypatch.setattr(
        runner,
        "build_slice3_admitted_plan_from_r9",
        admitted_plan_builder,
    )
    monkeypatch.setattr(runner, "build_slice3_admission_chain", admission_builder)
    monkeypatch.setattr(
        runner,
        "production_slice3_admission_store",
        lambda: admission_store,
    )
    monkeypatch.setattr(
        runner,
        "build_slice3_activation_manifest",
        activation_builder,
    )
    monkeypatch.setattr(
        runner,
        "production_slice3_activation_store",
        lambda: activation_store,
    )
    monkeypatch.setattr(
        runner, "FileSlice3ActionClaimStore", lambda _path: action_store
    )
    monkeypatch.setattr(runner, "FileSlice3ReadJournal", lambda _path: read_journal)
    monkeypatch.setattr(
        runner,
        "FileSlice3TerminalArtifactStore",
        lambda _path: terminal_store,
    )
    monkeypatch.setattr(runner, "StrictSlice3CoinbasePort", Port)
    monkeypatch.setattr(runner, "Slice3TerminalRoundtripOrchestrator", Orchestrator)
    monkeypatch.setattr(
        runner,
        "OPERATOR_AUTHORIZATION_SHA256",
        hashlib.sha256(b"authorized").hexdigest(),
    )
    monkeypatch.setattr(
        runner,
        "_validate_audited_state",
        lambda: ("b" * 40, "2" * 64),
    )
    monkeypatch.setattr(runner, "AUDITED_BACKEND_REVISION", "a" * 40)
    monkeypatch.setattr(runner, "AUDITED_OPENAPI_SHA256", "2" * 64)
    sanitized_result = runner.SanitizedSlice3Result(
        status="restored_baseline",
        reason_code="restored_baseline",
        terminal_artifact_sha256="8" * 64,
        terminal_evidence=MappingProxyType(
            _terminal_envelope("restored_baseline")
        ),
    )
    monkeypatch.setattr(
        runner,
        "_sanitize_slice3_result",
        lambda value, *, plan, now: sanitized_result,
    )

    result = runner.run_accepted_slice3_handoff(
        ephemeral_evidence={"ephemeral": True},
        persisted_terminal={"persisted": True},
        accepted_session=accepted_session,
        deferred_session=SimpleNamespace(),
        r9_store=SimpleNamespace(),
        callback_capability=object(),
        authorization_bytes=b"authorized",
        r9_artifact_file_sha256=_SHA_A,
        now=_NOW,
        handoff_terminalizer=_new_handoff_terminalizer(tmp_path),
    )

    assert result is sanitized_result
    assert result.terminal_evidence == _terminal_envelope("restored_baseline")
    assert len(ports) == 1
    handoff_rows = (
        tmp_path / "accepted-handoff.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert json.loads(handoff_rows[-1])["status"] == "delegated"
    assert events == [
        "r9_binding",
        "plan",
        "admission_chain",
        "admission_seal",
        "activation_manifest",
        "activation_seal",
        "orchestrator",
        "port",
        "run",
    ]


@dataclass
class _FakeAcceptedSession:
    delegate: object
    account_binding: object


def test_confirmed_workflow_passes_exact_accepted_session_to_handoff_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    authorization_bytes = runner.OPERATOR_AUTHORIZATION_PATH.read_bytes()
    accepted_session = _FakeAcceptedSession(object(), object())
    take_calls: list[tuple[object, object]] = []
    handoff_calls: list[dict[str, object]] = []
    suppression_events: list[str] = []
    prepared_session = object()
    preparation_calls = 0

    @contextmanager
    def suppression():
        suppression_events.append("enter")
        try:
            yield
        finally:
            suppression_events.append("exit")

    @contextmanager
    def signal_deferral():
        suppression_events.append("signal_enter")
        try:
            yield
        finally:
            suppression_events.append("signal_exit")

    class Deferred:
        hydrated = False

        def take_accepted_session(self, ephemeral, persisted):
            self.hydrated = True
            take_calls.append((ephemeral, persisted))
            return accepted_session

    deferred = Deferred()

    def prepare_session():
        nonlocal preparation_calls
        preparation_calls += 1
        return prepared_session

    def build_deferred(*, store, prepared_session: object):
        assert store.path == runner.FIXED_ATTEMPT_PATHS[0]
        assert prepared_session is globals_prepared_session
        return deferred

    globals_prepared_session = prepared_session

    class Store:
        path = runner.FIXED_ATTEMPT_PATHS[0]

        def read_completed(self):
            return {
                "status": "accepted",
                "outcome": "accepted",
                "evidence_sha256": _SHA_A,
            }

    class Producer:
        def run(self, *, accepted_callback):
            suppression_events.append("producer_run")
            ephemeral = {"status": "accepted", "private": "ephemeral"}
            persisted = {
                "status": "accepted",
                "outcome": "accepted",
                "evidence_sha256": _SHA_A,
            }
            accepted_callback(ephemeral, persisted)
            return persisted

    monkeypatch.setattr(
        runner,
        "build_deferred_r9_session",
        build_deferred,
    )
    monkeypatch.setattr(runner, "_prepare_r9_canonical_session", prepare_session)
    monkeypatch.setattr(runner, "_build_r9_store", lambda: Store())
    monkeypatch.setattr(
        runner,
        "_build_r9_producer",
        lambda *, deferred_session, store: Producer(),
    )
    monkeypatch.setattr(
        runner,
        "_sha256_file",
        lambda path: (
            _SHA_B
            if path == runner.FUTURES_PREVIEW_R9_ARTIFACT_PATH
            else hashlib.sha256(path.read_bytes()).hexdigest()
        ),
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "_suppress_coinbase_sdk_logging",
        suppression,
    )
    monkeypatch.setattr(
        runner,
        "_defer_slice3_termination_signals",
        signal_deferral,
    )

    result_marker = runner.SanitizedSlice3Result(
        status="restored_baseline",
        reason_code="restored_baseline",
        terminal_artifact_sha256=_SHA_A,
        terminal_evidence=MappingProxyType(
            _terminal_envelope("restored_baseline")
        ),
    )

    def fake_handoff(**kwargs):
        handoff_calls.append(kwargs)
        return kwargs["handoff_terminalizer"].delegate(
            lambda: result_marker,
            now=lambda: _NOW,
        )

    monkeypatch.setattr(runner, "run_accepted_slice3_handoff", fake_handoff)

    result = runner.execute_confirmed_workflow(
        authorization_bytes=authorization_bytes,
        now_provider=lambda: _NOW,
    )

    assert result.terminal == {
        "status": "accepted",
        "outcome": "accepted",
        "evidence_sha256": _SHA_A,
    }
    assert result.slice3_result == runner.SanitizedSlice3Result(
        status="restored_baseline",
        reason_code="restored_baseline",
        terminal_artifact_sha256=_SHA_A,
        terminal_evidence=MappingProxyType(
            _terminal_envelope("restored_baseline")
        ),
    )
    assert len(take_calls) == 1
    assert preparation_calls == 1
    assert len(handoff_calls) == 1
    assert handoff_calls[0]["accepted_session"] is accepted_session
    assert handoff_calls[0]["deferred_session"] is deferred
    assert handoff_calls[0]["r9_store"].path == runner.FIXED_ATTEMPT_PATHS[0]
    assert handoff_calls[0]["authorization_bytes"] == authorization_bytes
    assert handoff_calls[0]["r9_artifact_file_sha256"] == _SHA_B
    assert suppression_events == [
        "signal_enter",
        "enter",
        "producer_run",
        "exit",
        "signal_exit",
    ]


def test_missing_preview_expiry_halts_at_plan_boundary_and_reports_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, paths = _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    mutation_calls = 0
    persisted = {
        "status": "accepted",
        "outcome": "accepted",
        "artifact_type": runner.FUTURES_PREVIEW_R9_ARTIFACT_TYPE,
        "evidence_sha256": _SHA_A,
    }

    class Deferred:
        def take_accepted_session(self, _ephemeral, _persisted):
            return SimpleNamespace(delegate=object(), account_binding=object())

    class Store:
        path = paths[0]

        def read_completed(self):
            return persisted

    class Producer:
        def run(self, *, accepted_callback):
            accepted_callback({"status": "accepted"}, dict(persisted))
            return dict(persisted)

    @contextmanager
    def no_side_effect_context():
        yield

    monkeypatch.setattr(runner, "_prepare_r9_canonical_session", object)
    monkeypatch.setattr(
        runner,
        "build_deferred_r9_session",
        lambda **_kwargs: Deferred(),
    )
    monkeypatch.setattr(runner, "_build_r9_store", Store)
    monkeypatch.setattr(
        runner,
        "_build_r9_producer",
        lambda **_kwargs: Producer(),
    )
    monkeypatch.setattr(
        runner,
        "_sha256_file",
        lambda path: (
            _SHA_B
            if path == runner.FUTURES_PREVIEW_R9_ARTIFACT_PATH
            else hashlib.sha256(path.read_bytes()).hexdigest()
        ),
    )
    monkeypatch.setattr(
        runner.r9_tool,
        "_suppress_coinbase_sdk_logging",
        no_side_effect_context,
    )
    monkeypatch.setattr(
        runner,
        "_defer_slice3_termination_signals",
        no_side_effect_context,
    )

    def missing_expiry_handoff(**kwargs):
        def fail_plan():
            raise runner.R9Slice3RunnerError(
                "slice3_handoff_preview_expiry_unavailable"
            )

        return kwargs["handoff_terminalizer"].call(
            runner.AcceptedHandoffStage.PLAN,
            fail_plan,
            now=lambda: _NOW,
        )

    monkeypatch.setattr(
        runner,
        "run_accepted_slice3_handoff",
        missing_expiry_handoff,
    )

    result = runner.execute_confirmed_workflow(
        authorization_bytes=authorization.read_bytes(),
        now_provider=lambda: _NOW,
    )
    summary = runner.safe_terminal_summary(result)

    assert mutation_calls == 0
    assert result.slice3_result is not None
    assert result.slice3_result.status == "handoff_halted"
    assert result.slice3_result.reason_code == "accepted_handoff_plan_failed"
    assert result.slice3_result.terminal_evidence is None
    assert result.slice3_result.terminal_artifact_sha256 == hashlib.sha256(
        paths[1].read_bytes()
    ).hexdigest()
    assert summary["status"] == "terminal_halted"
    assert summary["slice3_status"] == "handoff_halted"
    assert summary["slice3_exchange_mutation_attempt_count"] == 0
    assert summary["slice3_terminal_evidence"] is None
    assert all(not path.exists() for path in paths[2:])


def test_real_r9_handoff_terminalizes_at_documented_expiry_plan_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    terminalizer = _new_handoff_terminalizer(tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(runner, "_runtime_enforces_admission_binding", lambda: True)
    monkeypatch.setattr(
        runner,
        "_validate_audited_state",
        lambda: ("a" * 40, _SHA_A),
    )
    monkeypatch.setattr(
        runner,
        "_consume_accepted_handoff_capability",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        runner,
        "_validate_accepted_handoff_provenance",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        runner,
        "StrictSlice3CoinbasePort",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("port constructed before documented expiry")
        ),
    )
    monkeypatch.setattr(
        runner,
        "OPERATOR_AUTHORIZATION_SHA256",
        hashlib.sha256(b"authorized").hexdigest(),
    )

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_accepted_handoff_blocked$",
    ):
        runner.run_accepted_slice3_handoff(
            ephemeral_evidence={
                "completed_at": _NOW.isoformat(),
                "preview_response": {},
            },
            persisted_terminal={},
            accepted_session=SimpleNamespace(
                delegate=object(),
                account_binding=object(),
            ),
            deferred_session=object(),
            r9_store=object(),
            callback_capability=object(),
            authorization_bytes=b"authorized",
            r9_artifact_file_sha256=_SHA_A,
            now=_NOW,
            handoff_terminalizer=terminalizer,
        )

    terminal = terminalizer.store.read_terminal_result()
    assert terminal.preview_generation == 9
    assert terminal.preview_artifact_type == (
        runner.FUTURES_PREVIEW_R9_ARTIFACT_TYPE
    )
    assert terminal.status == "halted"
    assert terminal.stage == "plan"
    assert terminal.reason_code == "accepted_handoff_plan_failed"


@pytest.mark.parametrize("reservation_exists", (False, True))
def test_offline_handoff_recovery_never_constructs_credentials_preview_or_ports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reservation_exists: bool,
) -> None:
    preview_path = tmp_path / "r9.jsonl"
    handoff_path = tmp_path / "accepted-handoff.jsonl"
    preview_path.write_bytes(b"sanitized accepted preview")
    successor_paths = tuple(
        tmp_path / name
        for name in (
            "admission.json",
            "activation.json",
            "actions.jsonl",
            "reads.jsonl",
            "terminal.json",
        )
    )
    if reservation_exists:
        reservation_store = runner.FileAcceptedHandoffArtifactStore(handoff_path)
        reservation = reservation_store.reserve(
            preview_generation=9,
            preview_artifact_type=runner.FUTURES_PREVIEW_R9_ARTIFACT_TYPE,
            preview_artifact_file_sha256=_SHA_B,
            preview_evidence_sha256=_SHA_A,
            now=_NOW,
        )
        reservation.release()
    preview_calls = 0
    credential_calls = 0
    port_calls = 0

    class PreviewStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def read_completed(self):
            return {
                "status": "accepted",
                "outcome": "accepted",
                "artifact_type": runner.FUTURES_PREVIEW_R9_ARTIFACT_TYPE,
                "evidence_sha256": _SHA_A,
            }

    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    monkeypatch.setattr(runner, "_validate_audited_state", lambda: ("a" * 40, _SHA_A))
    monkeypatch.setattr(runner, "FUTURES_PREVIEW_R9_ARTIFACT_PATH", preview_path)
    monkeypatch.setattr(runner, "ACCEPTED_HANDOFF_ARTIFACT_PATH", handoff_path)
    monkeypatch.setattr(runner, "SLICE3_ADMISSION_ARTIFACT_PATH", successor_paths[0])
    monkeypatch.setattr(runner, "SLICE3_ACTIVATION_ARTIFACT_PATH", successor_paths[1])
    monkeypatch.setattr(runner, "SLICE3_ACTION_JOURNAL_PATH", successor_paths[2])
    monkeypatch.setattr(runner, "SLICE3_READ_JOURNAL_PATH", successor_paths[3])
    monkeypatch.setattr(runner, "SLICE3_TERMINAL_EVIDENCE_PATH", successor_paths[4])
    monkeypatch.setattr(runner, "FuturesOrderPreviewArtifactStore", PreviewStore)
    monkeypatch.setattr(runner, "_sha256_file", lambda _path: _SHA_B)
    monkeypatch.setattr(
        runner,
        "_prepare_r9_canonical_session",
        lambda: (_ for _ in ()).throw(AssertionError("credential construction")),
    )
    monkeypatch.setattr(
        runner,
        "_build_r9_producer",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("Preview rerun")),
    )
    monkeypatch.setattr(
        runner,
        "StrictSlice3CoinbasePort",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("port construction")
        ),
    )

    result = runner.recover_r9_accepted_handoff_offline(
        now_provider=lambda: _NOW,
    )

    assert preview_calls == credential_calls == port_calls == 0
    assert result.status == "handoff_halted"
    assert result.reason_code == "accepted_handoff_delegation_failed"
    assert result.terminal_evidence is None
    assert len(handoff_path.read_text(encoding="utf-8").splitlines()) == 2
    assert all(not path.exists() for path in successor_paths)


def test_confirmed_workflow_does_not_take_session_when_r9_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_clean_preflight(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)

    class Deferred:
        def take_accepted_session(self, *_args):
            raise AssertionError("accepted session taken")

    class Store:
        path = runner.FIXED_ATTEMPT_PATHS[0]

        def read_completed(self):
            return {"status": "blocked", "outcome": "blocked"}

    class Producer:
        def run(self, *, accepted_callback):
            del accepted_callback
            raise runner.FuturesOrderPreviewArtifactError("PRIVATE FAILURE")

    monkeypatch.setattr(
        runner,
        "build_deferred_r9_session",
        lambda **_kwargs: Deferred(),
    )
    monkeypatch.setattr(
        runner,
        "_prepare_r9_canonical_session",
        lambda: object(),
    )
    monkeypatch.setattr(runner, "_build_r9_store", Store)
    monkeypatch.setattr(
        runner,
        "_build_r9_producer",
        lambda *, deferred_session, store: Producer(),
    )

    result = runner.execute_confirmed_workflow(
        authorization_bytes=runner.OPERATOR_AUTHORIZATION_PATH.read_bytes(),
        now_provider=lambda: _NOW,
    )

    assert result.terminal == {"status": "blocked", "outcome": "blocked"}
    assert result.slice3_result is None


def test_safe_summary_never_includes_raw_identifiers_or_exception_text() -> None:
    summary = runner.safe_terminal_summary(
        runner.EndToEndExecutionResult(
            terminal={
                "status": "accepted",
                "outcome": "accepted",
                "preview_id": "PRIVATE_PREVIEW_ID",
                "portfolio_id": "PRIVATE_PORTFOLIO_ID",
                "blocker": "PRIVATE_EXCEPTION_TEXT",
            },
            slice3_result=runner.SanitizedSlice3Result(
                status="halted",
                reason_code="final_reconciliation_incomplete",
                terminal_artifact_sha256=_SHA_A,
                terminal_evidence=MappingProxyType(
                    _terminal_envelope("halted")
                ),
            ),
        )
    )

    rendered = json.dumps(summary, sort_keys=True)
    assert "PRIVATE_" not in rendered
    assert summary["r9_status"] == "accepted"
    assert summary["slice3_status"] == "halted"
    assert summary["slice3_reason_code"] == "final_reconciliation_incomplete"


def test_signal_deferral_blocks_fixed_set_on_main_thread_and_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_thread = object()
    calls: list[tuple[object, frozenset[object]]] = []
    previous_mask = frozenset({object()})

    monkeypatch.setattr(runner.threading, "main_thread", lambda: main_thread)
    monkeypatch.setattr(runner.threading, "current_thread", lambda: main_thread)

    def pthread_sigmask(how, signals):
        calls.append((how, frozenset(signals)))
        return previous_mask

    monkeypatch.setattr(runner.signal, "pthread_sigmask", pthread_sigmask)

    with runner._defer_slice3_termination_signals():
        assert len(calls) == 1
        assert calls[0][0] == runner.signal.SIG_BLOCK
        assert calls[0][1] == frozenset(runner._SLICE3_DEFERRED_SIGNALS)

    assert calls == [
        (runner.signal.SIG_BLOCK, frozenset(runner._SLICE3_DEFERRED_SIGNALS)),
        (runner.signal.SIG_SETMASK, previous_mask),
    ]


def test_signal_deferral_rejects_non_main_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.threading, "main_thread", lambda: object())
    monkeypatch.setattr(runner.threading, "current_thread", lambda: object())

    with pytest.raises(
        runner.R9Slice3RunnerError,
        match="^futures_r9_slice3_signal_deferral_unavailable$",
    ):
        with runner._defer_slice3_termination_signals():
            raise AssertionError("unreachable")


def test_outer_cli_baseexception_is_fixed_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        runner,
        "main",
        lambda _argv=None: (_ for _ in ()).throw(
            KeyboardInterrupt("PRIVATE_SIGNAL_CONTEXT")
        ),
    )

    assert runner._cli_entrypoint(["--preflight"]) == 2
    rendered = capsys.readouterr().err
    assert "PRIVATE_SIGNAL_CONTEXT" not in rendered
    assert "Traceback" not in rendered
    assert json.loads(rendered)["blocker"] == (
        "futures_r9_slice3_outer_baseexception_blocked"
    )


@pytest.mark.parametrize(
    ("slice3_status", "expected_status", "expected_exit"),
    [
        ("restored_baseline", "terminal_restored", 0),
        ("halted", "terminal_halted", 2),
        ("unknown", "terminal_halted", 2),
    ],
)
def test_cli_exit_matches_slice3_terminal_state(
    slice3_status: str,
    expected_status: str,
    expected_exit: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    preflight = runner.PreflightEvidence(
        authorization_bytes=b"authorized",
        backend_revision="b" * 40,
        openapi_sha256=_SHA_A,
    )
    monkeypatch.setattr(runner, "validate_production_preflight", lambda: preflight)
    monkeypatch.setattr(
        runner,
        "execute_confirmed_workflow",
        lambda **_kwargs: runner.EndToEndExecutionResult(
            terminal={"status": "accepted", "outcome": "accepted"},
            slice3_result=runner.SanitizedSlice3Result(
                status=slice3_status,
                reason_code=(
                    "restored_baseline"
                    if slice3_status == "restored_baseline"
                    else "final_reconciliation_incomplete"
                ),
                terminal_artifact_sha256=_SHA_A,
                terminal_evidence=(
                    MappingProxyType(_terminal_envelope(slice3_status))
                    if slice3_status in {"restored_baseline", "halted"}
                    else None
                ),
            ),
        ),
    )

    assert runner.main(["--confirm-one-r9-preview-and-slice3"]) == expected_exit
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == expected_status


def test_r9_nonacceptance_is_terminal_no_mutation_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "R9_SLICE3_END_TO_END_READY", True)
    preflight = runner.PreflightEvidence(
        authorization_bytes=b"authorized",
        backend_revision="b" * 40,
        openapi_sha256=_SHA_A,
    )
    monkeypatch.setattr(runner, "validate_production_preflight", lambda: preflight)
    monkeypatch.setattr(
        runner,
        "execute_confirmed_workflow",
        lambda **_kwargs: runner.EndToEndExecutionResult(
            terminal={"status": "blocked", "outcome": "blocked"},
            slice3_result=None,
        ),
    )

    assert runner.main(["--confirm-one-r9-preview-and-slice3"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "terminal_no_mutation"
    assert summary["slice3_status"] == "not_run"
