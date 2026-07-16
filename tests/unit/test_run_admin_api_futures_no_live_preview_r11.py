"""Focused synthetic safety tests for the one-use Slice 2R11 Preview tool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from application.admin_api import futures_order_preview as preview_module
from application.admin_api.futures_order_preview import (
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
)
from application.admin_api.models import AdminFuturesOrderPreviewResponse
from tests.unit.test_admin_api_futures_order_preview import (
    NOW,
    _r8_compatible_rest_client,
)
from tools import run_admin_api_futures_no_live_preview_r11 as r11_tool


_EXPECTED_R11_AUDITED_COMPONENTS = {
    "backend:.agents/ownership.yaml",
    "backend:api/v1/routes/futures.py",
    "backend:application/admin_api/futures_order_preview.py",
    "backend:application/admin_api/models.py",
    "backend:docs/FUTURES_SLICE_2R11_PREPARATION.md",
    "backend:external/coinbase_client.py",
    "backend:genai_data/AGENT_MVP_REBUILD_GOAL.md",
    "backend:openapi/coinbase-admin-api.yaml",
    "backend:pyproject.toml",
    "backend:tests/unit/test_admin_api_futures_order_preview.py",
    "backend:tests/unit/test_run_admin_api_futures_no_live_preview_r11.py",
    "backend:tests/regression/test_spot_readiness_gate.py",
    "backend:tools/run_admin_api_futures_no_live_preview.py",
    "backend:tools/run_autonomous_work_queue_check.py",
    "frontend:AGENTS.md",
    "frontend:docs/CURRENT_MVP_GOAL.md",
    "frontend:docs/TESTING.md",
    "frontend:scripts/check-autonomous-work-queue.mjs",
    "frontend:scripts/check-deployment-readiness.mjs",
    "frontend:scripts/check-mvp-goal-alignment.mjs",
    "frontend:scripts/run-vitest.mjs",
    "frontend:src/features/futures-perpetuals/FuturesPerpetualsReadModel.tsx",
    "frontend:src/features/futures-perpetuals/futuresPerpetualsBackendAdapters.ts",
    "frontend:src/shared/api/generated/schema.ts",
    "frontend:src/shared/quality/artifactContract.json",
    "frontend:src/shared/quality/deploymentReadiness.ts",
    "frontend:tests/unit/FuturesOrderPreviewReadback.test.tsx",
    "frontend:tests/unit/qualityGates.test.tsx",
    "frontend:vitest.config.ts",
}

_EXPECTED_SDK_SOURCE_SHA256 = {
    "coinbase/rest/orders.py": (
        "c3d34a3583dea07d69f9f06c5691be02f77b08d3a37b102b40666090e40cea06"
    ),
    "coinbase/rest/rest_base.py": (
        "05708e76001707ea56c45ec680ac5305b2a51061ed0122840f446930845d1cec"
    ),
    "coinbase/rest/types/base_response.py": (
        "89e40f2f95020a5ea1a4323200a2473c30681b9de4ce8a0de561ec4c739e5989"
    ),
    "coinbase/rest/types/orders_types.py": (
        "19552322d672d194aad8cf91b7a07038360c6d9504ac4fce1e7524b7728317b2"
    ),
}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def test_r11_audit_binding_expression_is_rejected_before_execution(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "activation-side-effect"
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    runner = tools_dir / "run_admin_api_futures_no_live_preview_r11.py"
    source = Path(r11_tool.__file__).read_text(encoding="utf-8")
    poisoned = source.replace(
        "    R11_PREVIEW_CALL_AUTHORITY_ACTIVE = False",
        "    R11_PREVIEW_CALL_AUTHORITY_ACTIVE = "
        f"__import__('pathlib').Path({str(marker)!r}).write_text("
        "'executed', encoding='utf-8')",
        1,
    )
    runner.write_text(poisoned, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-I", str(runner), "--preflight"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "futures_preview_r11_bootstrap_source_invalid" in completed.stderr
    assert marker.exists() is False


def test_r11_direct_execution_requires_isolated_python_before_stdlib_imports(
    tmp_path: Path,
) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    runner = tools_dir / "run_admin_api_futures_no_live_preview_r11.py"
    runner.write_bytes(Path(r11_tool.__file__).read_bytes())
    marker = tmp_path / "stdlib-shadow-executed"
    (tools_dir / "argparse.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(runner), "--preflight"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "futures_preview_r11_isolated_runtime_required" in completed.stderr
    assert marker.exists() is False


def test_r11_isolated_bootstrap_rejects_unclean_source_before_project_imports(
    tmp_path: Path,
) -> None:
    tools_dir = tmp_path / "tools"
    application_dir = tmp_path / "application" / "admin_api"
    tools_dir.mkdir()
    application_dir.mkdir(parents=True)
    runner = tools_dir / "run_admin_api_futures_no_live_preview_r11.py"
    runner.write_bytes(Path(r11_tool.__file__).read_bytes())
    marker = tmp_path / "project-import-executed"
    (application_dir / "futures_order_preview.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-I", str(runner), "--preflight"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "futures_preview_r11_bootstrap_source_invalid" in completed.stderr
    assert marker.exists() is False


def _synthetic_audit_binding_block(*, active: bool) -> bytes:
    values = {
        "R11_PREPARATION_REVISION": _sha("prepared-backend-revision"),
        "R11_FRONTEND_REVISION": _sha("prepared-frontend-revision"),
        "R11_NORMALIZED_RUNNER_SHA256": _sha("normalized-runner"),
        "R11_AUTHORIZATION_SHA256": _sha("bounded-r11-authorization"),
        "R11_SAFETY_AUDIT_RECEIPT_SHA256": _sha("independent-safety-audit"),
        "R11_BLIND_AUDIT_RECEIPT_SHA256": _sha("blind-contextless-audit"),
    }
    lines = [
        "# BEGIN R11 AUDIT BINDINGS",
        "if False:",
        f"    R11_PREVIEW_CALL_AUTHORITY_ACTIVE = {active!r}",
        f"    R11_FINAL_AUDIT_BINDING_READY = {active!r}",
    ]
    lines.extend(
        f'    {name} = "{value if active else ""}"'
        for name, value in values.items()
    )
    lines.append(
        '    R11_ACTIVATION_NOT_AFTER = "2999-01-01T00:00:00Z"'
        if active
        else '    R11_ACTIVATION_NOT_AFTER = ""'
    )
    if active:
        lines.append("    R11_AUDITED_COMPONENT_SHA256: dict[str, str] = {")
        lines.extend(
            f'        "{component}": "{_sha(component)}",'
            for component in sorted(_EXPECTED_R11_AUDITED_COMPONENTS)
        )
        lines.append("    }")
    else:
        lines.append("    R11_AUDITED_COMPONENT_SHA256: dict[str, str] = {}")
    lines.append("# END R11 AUDIT BINDINGS")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _bind_valid_r11_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, str], dict[str, str]]:
    monkeypatch.setattr(r11_tool, "_R11_CLI_BOOTSTRAP_VALIDATED", True)
    values = {
        "preparation": _sha("prepared-backend-revision"),
        "frontend": _sha("prepared-frontend-revision"),
        "runner": _sha("normalized-runner"),
        "authorization": _sha("bounded-r11-authorization"),
        "safety": _sha("independent-safety-audit"),
        "blind": _sha("blind-contextless-audit"),
        "activation": _sha("constants-only-activation-commit"),
    }
    components = {
        component: _sha(component)
        for component in _EXPECTED_R11_AUDITED_COMPONENTS
    }
    monkeypatch.setattr(r11_tool, "R11_PREVIEW_CALL_AUTHORITY_ACTIVE", True)
    monkeypatch.setattr(r11_tool, "R11_FINAL_AUDIT_BINDING_READY", True)
    monkeypatch.setattr(
        r11_tool,
        "R11_PREPARATION_REVISION",
        values["preparation"],
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_FRONTEND_REVISION",
        values["frontend"],
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_NORMALIZED_RUNNER_SHA256",
        values["runner"],
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_AUTHORIZATION_SHA256",
        values["authorization"],
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_SAFETY_AUDIT_RECEIPT_SHA256",
        values["safety"],
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_BLIND_AUDIT_RECEIPT_SHA256",
        values["blind"],
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_ACTIVATION_NOT_AFTER",
        "2999-01-01T00:00:00Z",
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_AUDITED_COMPONENT_SHA256",
        components,
    )
    monkeypatch.setattr(
        r11_tool,
        "normalized_runner_sha256",
        lambda: values["runner"],
    )
    monkeypatch.setattr(
        r11_tool,
        "current_audited_component_sha256",
        lambda: dict(components),
    )
    monkeypatch.setattr(
        r11_tool,
        "_repository_is_clean_synced_main",
        lambda _root: True,
    )
    monkeypatch.setattr(r11_tool, "_validate_sdk_pin", lambda: None)

    def git_output(root: Path, *args: str) -> str:
        if root == r11_tool.FRONTEND_ROOT and args == ("rev-parse", "HEAD"):
            return values["frontend"]
        if root == r11_tool.REPO_ROOT and args == ("rev-parse", "HEAD"):
            return values["activation"]
        if root == r11_tool.REPO_ROOT and args == ("rev-parse", "HEAD^"):
            return values["preparation"]
        if root == r11_tool.REPO_ROOT and args[:4] == (
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
        ):
            return r11_tool._R11_RUNNER_RELATIVE_PATH
        raise AssertionError((root, args))

    monkeypatch.setattr(r11_tool, "_git_output", git_output)
    return components, values


def test_r11_normalized_runner_hash_ignores_only_literal_audit_bindings() -> None:
    first = b"before\n" + _synthetic_audit_binding_block(active=False) + b"after\n"
    activated = (
        b"before\n" + _synthetic_audit_binding_block(active=True) + b"after\n"
    )
    logic_changed = activated.replace(b"after\n", b"changed-after\n")

    first_normalized = r11_tool._normalized_runner_bytes(first)
    activated_normalized = r11_tool._normalized_runner_bytes(activated)

    assert first_normalized == activated_normalized
    assert hashlib.sha256(first_normalized).digest() == hashlib.sha256(
        activated_normalized
    ).digest()
    assert r11_tool._normalized_runner_bytes(logic_changed) != first_normalized


@pytest.mark.parametrize(
    "injected_source",
    [
        b'raise RuntimeError("activation-side-effect")\n',
        b'R11_PREPARATION_REVISION = "duplicate"\n',
        b'R11_PREPARATION_REVISION = str()\n',
    ],
)
def test_r11_normalized_runner_rejects_nonliteral_or_extra_activation_code(
    injected_source: bytes,
) -> None:
    block = _synthetic_audit_binding_block(active=False)
    poisoned = block.replace(
        b"# END R11 AUDIT BINDINGS\n",
        injected_source + b"# END R11 AUDIT BINDINGS\n",
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="literal audit binding block is invalid",
    ):
        r11_tool._normalized_runner_bytes(b"before\n" + poisoned + b"after\n")


def test_r11_normalized_runner_rejects_duplicate_component_literal() -> None:
    block = _synthetic_audit_binding_block(active=True)
    component = sorted(_EXPECTED_R11_AUDITED_COMPONENTS)[0]
    line = f'        "{component}": "{_sha(component)}",\n'.encode("utf-8")
    poisoned = block.replace(line, line + line)

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="literal audit binding block is invalid",
    ):
        r11_tool._normalized_runner_bytes(b"before\n" + poisoned + b"after\n")


def test_r11_normalized_runner_rejects_executable_activation_wrapper() -> None:
    poisoned = _synthetic_audit_binding_block(active=False).replace(
        b"if False:\n",
        b"if True:\n",
        1,
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="literal audit binding block is invalid",
    ):
        r11_tool._normalized_runner_bytes(b"before\n" + poisoned + b"after\n")


def test_r11_isolated_bootstrap_ignores_local_sitecustomize(
    tmp_path: Path,
) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    runner = tools_dir / "run_admin_api_futures_no_live_preview_r11.py"
    runner.write_bytes(Path(r11_tool.__file__).read_bytes())
    marker = tmp_path / "sitecustomize-executed"
    (tmp_path / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-I", str(runner), "--preflight"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "futures_preview_r11_bootstrap_source_invalid" in completed.stderr
    assert marker.exists() is False


def test_r11_bootstrap_dependency_site_binds_sdk_before_project_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected: dict[str, str] = {}
    for relative in _EXPECTED_SDK_SOURCE_SHA256:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"synthetic:{relative}\n", encoding="utf-8")
        expected[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "coinbase_advanced_py-1.8.4.dist-info").mkdir()
    monkeypatch.setattr(r11_tool, "_R11_DEPENDENCY_SITE", tmp_path)
    monkeypatch.setattr(r11_tool, "_R11_SDK_SOURCE_SHA256", expected)

    assert r11_tool._bootstrap_dependency_site_is_valid() is True

    first = tmp_path / next(iter(expected))
    first.write_text("drifted-sdk-source\n", encoding="utf-8")
    assert r11_tool._bootstrap_dependency_site_is_valid() is False


def test_r11_audited_component_manifest_covers_all_material_surfaces() -> None:
    assert r11_tool._R11_EXPECTED_COMPONENTS == frozenset(
        _EXPECTED_R11_AUDITED_COMPONENTS
    )


def test_r11_production_path_rejects_environment_redirection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_ROOT",
        str(tmp_path),
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="fixed production artifact path is invalid",
    ):
        r11_tool.production_artifact_path()


def test_r11_clean_revision_gate_rejects_untracked_backend_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = _sha("backend-main")

    def git_output(_root: Path, *args: str) -> str:
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("rev-parse", "HEAD") or args == (
            "rev-parse",
            "origin/main",
        ):
            return revision
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        if args == ("ls-files", "--others", "--exclude-standard"):
            return "rogue_runtime_override.py"
        raise AssertionError(args)

    monkeypatch.setattr(r11_tool, "_git_output", git_output)

    assert r11_tool._repository_is_clean_synced_main(r11_tool.REPO_ROOT) is False


def test_r11_clean_revision_gate_binds_only_exact_inert_frontend_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "coinbase-admin-live-root-child-chain-2026-07-11.png": (
            "a38b6a6bdca3073cca7245cfece2783b82e9414267bff421fcd97ad7d5e79cec"
        ),
        "coinbase-admin-live-root-child-chain-complete-2026-07-12.png": (
            "5b0057de8d4e9e0757341cdb95dcaace979cef72f12f3da2cda9f1b72c5697b6"
        ),
        "coinbase-admin-spot-operations-2026-07-11.png": (
            "4c65c473dd7cd3ffb155a6623545578f08cd6caf72db43c387b5bcc7da131244"
        ),
        "selected-order-execution-closeout-v14.png": (
            "020fa080228ab52ab3d318fda112e48efb1f27532418e999abfdb4bd54cbbb1d"
        ),
    }
    revision = _sha("frontend-main")

    def git_output(_root: Path, *args: str) -> str:
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("rev-parse", "HEAD") or args == (
            "rev-parse",
            "origin/main",
        ):
            return revision
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        if args == ("ls-files", "--others", "--exclude-standard"):
            return "\n".join(sorted(expected))
        raise AssertionError(args)

    monkeypatch.setattr(r11_tool, "_git_output", git_output)
    monkeypatch.setattr(
        r11_tool,
        "_file_sha256",
        lambda path: (
            _sha("drifted-user-image")
            if path.name == "selected-order-execution-closeout-v14.png"
            else expected[path.name]
        ),
    )

    assert r11_tool._FRONTEND_INERT_UNTRACKED_SHA256 == expected
    assert (
        r11_tool._repository_is_clean_synced_main(r11_tool.FRONTEND_ROOT)
        is False
    )


def test_r11_sdk_pin_binds_official_v1_8_4_preview_path_source_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert r11_tool._R11_SDK_SOURCE_SHA256 == _EXPECTED_SDK_SOURCE_SHA256

    monkeypatch.setattr(r11_tool, "version", lambda _name: "1.8.4")
    monkeypatch.setattr(
        r11_tool,
        "_installed_sdk_source_sha256",
        lambda: {
            **_EXPECTED_SDK_SOURCE_SHA256,
            "coinbase/rest/orders.py": _sha("locally-drifted-sdk-source"),
        },
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="SDK binding is invalid",
    ):
        r11_tool._validate_sdk_pin()


@pytest.mark.parametrize(
    ("safety_receipt", "blind_receipt"),
    [
        ("", _sha("blind-contextless-audit")),
        (_sha("independent-safety-audit"), ""),
        (_sha("same-audit-receipt"), _sha("same-audit-receipt")),
    ],
)
def test_r11_final_binding_requires_distinct_nonempty_audit_receipts(
    monkeypatch: pytest.MonkeyPatch,
    safety_receipt: str,
    blind_receipt: str,
) -> None:
    _bind_valid_r11_audit(monkeypatch)
    monkeypatch.setattr(
        r11_tool,
        "R11_SAFETY_AUDIT_RECEIPT_SHA256",
        safety_receipt,
    )
    monkeypatch.setattr(
        r11_tool,
        "R11_BLIND_AUDIT_RECEIPT_SHA256",
        blind_receipt,
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="final audit binding is invalid",
    ):
        r11_tool._validate_final_audit_binding()


@pytest.mark.parametrize("drift", ["runner", "openapi", "frontend_revision"])
def test_r11_final_binding_rejects_runner_openapi_or_revision_drift(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    components, _values = _bind_valid_r11_audit(monkeypatch)
    if drift == "runner":
        monkeypatch.setattr(
            r11_tool,
            "normalized_runner_sha256",
            lambda: _sha("runner-logic-drift"),
        )
    elif drift == "openapi":
        drifted = dict(components)
        drifted["backend:openapi/coinbase-admin-api.yaml"] = _sha(
            "changed-openapi-contract"
        )
        monkeypatch.setattr(
            r11_tool,
            "current_audited_component_sha256",
            lambda: drifted,
        )
    else:
        original_git_output = r11_tool._git_output

        def revision_drift(root: Path, *args: str) -> str:
            if root == r11_tool.FRONTEND_ROOT and args == (
                "rev-parse",
                "HEAD",
            ):
                return _sha("unexpected-frontend-revision")
            return original_git_output(root, *args)

        monkeypatch.setattr(r11_tool, "_git_output", revision_drift)

    with pytest.raises(FuturesOrderPreviewArtifactError):
        r11_tool._validate_final_audit_binding()


def test_r11_final_binding_rejects_expired_activation_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_valid_r11_audit(monkeypatch)
    monkeypatch.setattr(
        r11_tool,
        "R11_ACTIVATION_NOT_AFTER",
        "2000-01-01T00:00:00Z",
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="activation environment is invalid",
    ):
        r11_tool._validate_final_audit_binding()


@pytest.mark.parametrize("commit_drift", ["parent", "changed_files"])
def test_r11_activation_commit_requires_preparation_parent_and_runner_only(
    monkeypatch: pytest.MonkeyPatch,
    commit_drift: str,
) -> None:
    _components, _values = _bind_valid_r11_audit(monkeypatch)
    original_git_output = r11_tool._git_output

    def activation_drift(root: Path, *args: str) -> str:
        if (
            commit_drift == "parent"
            and root == r11_tool.REPO_ROOT
            and args == ("rev-parse", "HEAD^")
        ):
            return _sha("unexpected-parent")
        if (
            commit_drift == "changed_files"
            and root == r11_tool.REPO_ROOT
            and args[:4]
            == ("diff-tree", "--no-commit-id", "--name-only", "-r")
        ):
            return "\n".join(
                (
                    r11_tool._R11_RUNNER_RELATIVE_PATH,
                    "application/admin_api/futures_order_preview.py",
                )
            )
        return original_git_output(root, *args)

    monkeypatch.setattr(r11_tool, "_git_output", activation_drift)

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="activation commit is invalid",
    ):
        r11_tool._validate_final_audit_binding()


def test_r11_preflight_is_offline_and_never_reserves_hydrates_or_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "fixed-r11-preview.jsonl"
    monkeypatch.setattr(r11_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING),
    )
    monkeypatch.setattr(
        r11_tool,
        "_build_r11_preview_rest_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("credential hydration or Coinbase client construction")
        ),
    )

    assert r11_tool.R11_PREVIEW_CALL_AUTHORITY_ACTIVE is False
    assert r11_tool.R11_FINAL_AUDIT_BINDING_READY is False
    assert r11_tool.main(["--preflight"]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "artifact_created": False,
        "artifact_path": str(path),
        "blocker": None,
        "claim_contract_ready": True,
        "coinbase_read_ran": False,
        "exchange_submission_attempt_count": 0,
        "final_audit_binding_ready": False,
        "live_authority_active": False,
        "live_coinbase_execution": "not_run",
        "predecessor_artifact": "futures_exact_no_live_preview_slice_2r10.jsonl",
        "predecessor_file_sha256": preview_module.FUTURES_PREVIEW_R10_FILE_SHA256,
        "preview_order_attempt_count": 0,
        "status": "prepared",
    }
    assert not path.exists()


def test_r11_confirmation_blocks_before_path_predecessor_or_client_until_activation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(label: str):
        return lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(label)
        )

    monkeypatch.setattr(
        r11_tool,
        "production_artifact_path",
        forbidden("R11 path inspected"),
    )
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        forbidden("R10 predecessor inspected"),
    )
    monkeypatch.setattr(
        r11_tool,
        "_build_r11_preview_rest_client",
        forbidden("credential hydration or Coinbase client construction"),
    )
    monkeypatch.setattr(r11_tool, "_R11_CLI_BOOTSTRAP_VALIDATED", True)

    assert r11_tool.main(["--confirm-one-r11-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    assert summary == {
        "artifact_created": False,
        "artifact_path": str(preview_module.FUTURES_PREVIEW_R11_ARTIFACT_PATH),
        "blocker": "futures_preview_r11_call_authority_inactive",
        "coinbase_read_ran": False,
        "exchange_submission_attempt_count": 0,
        "live_coinbase_execution": "not_run",
        "preview_order_attempt_count": 0,
        "status": "blocked",
    }


def test_r11_imported_confirmation_requires_cli_bootstrap_before_all_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(label: str):
        return lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(label)
        )

    monkeypatch.setattr(r11_tool, "_R11_CLI_BOOTSTRAP_VALIDATED", False)
    monkeypatch.setattr(
        r11_tool,
        "production_artifact_path",
        forbidden("R11 path inspected"),
    )
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        forbidden("R10 predecessor inspected"),
    )
    monkeypatch.setattr(
        r11_tool,
        "_build_r11_preview_rest_client",
        forbidden("credential hydration or Coinbase client construction"),
    )

    assert r11_tool.main(["--confirm-one-r11-preview"]) == 2

    summary = json.loads(capsys.readouterr().err)
    assert summary["blocker"] == (
        "futures_preview_r11_bootstrap_validation_required"
    )


def test_r11_deferred_client_requires_exclusive_r11_claim_before_hydration(
    tmp_path: Path,
) -> None:
    hydration_attempts = 0

    def forbidden_factory():
        nonlocal hydration_attempts
        hydration_attempts += 1
        raise AssertionError("session hydrated without an R11 claim")

    deferred = r11_tool.DeferredR11PreviewRestClient(
        store=FuturesOrderPreviewArtifactStore(tmp_path / "absent-r11.jsonl"),
        client_factory=forbidden_factory,
    )

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="R11 claim is unavailable",
    ):
        deferred.get_api_key_permissions()

    assert hydration_attempts == 0


def test_r11_synthetic_accepted_session_is_exactly_bounded_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegate = _r8_compatible_rest_client()
    delegate.preview_response["is_max"] = False
    path = tmp_path / "accepted-r11.jsonl"
    store = r11_tool.build_r11_store(path)
    preview_client = r11_tool.FuturesPreviewOnlyRestClient(delegate)
    deferred = r11_tool.DeferredR11PreviewRestClient(
        store=store,
        prepared_client=preview_client,
    )
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING),
    )
    producer = r11_tool.build_r11_producer(
        rest_client=deferred,
        store=store,
        now=lambda: NOW,
        correlation_id_factory=lambda: (
            "299cb4b8-b99d-4663-baa8-da9db777e611"
        ),
        idempotency_key_factory=lambda: (
            "eb47c508-d834-44bc-9732-138cf6077118"
        ),
    )

    terminal = producer.run()

    assert terminal == store.read_completed()
    assert terminal["artifact_type"] == (
        preview_module.FUTURES_PREVIEW_R11_ARTIFACT_TYPE
    )
    assert terminal["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING
    )
    assert terminal["status"] == terminal["outcome"] == "accepted"
    assert terminal["preview_response"]["preview_id"] == "withheld"
    assert len(terminal["preview_id_sha256"]) == 64
    assert terminal["attempt_counters"] == {
        "preview_order": 1,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert terminal["exchange_submission_attempt_count"] == 0
    assert terminal["submitted_notional_usdc"] == "0"
    assert terminal["executed_notional_usdc"] == "0"
    assert len(delegate.preview_calls) == 1
    assert delegate.forbidden_calls == []
    assert path.stat().st_mode & 0o777 == 0o400
    assert "preview-avp-1" not in path.read_text(encoding="utf-8")
    AdminFuturesOrderPreviewResponse.model_validate(terminal)

    public_callables = {
        name
        for name in dir(type(deferred))
        if not name.startswith("_") and callable(getattr(type(deferred), name))
    }
    assert public_callables == {
        "get_api_key_permissions",
        "list_portfolios",
        "get_product_dict",
        "get_best_bid_ask",
        "get_futures_positions",
        "get_futures_margin_collateral_snapshot",
        "preview_order",
    }
    assert not hasattr(deferred, "take_accepted_session")
    assert not hasattr(deferred, "create_order")
    assert not hasattr(deferred, "__dict__")


def test_r11_unknown_preview_is_value_blind_consumed_and_cannot_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_text = "PRIVATE-R11-UNKNOWN-TEXT"
    delegate = _r8_compatible_rest_client()
    delegate.preview_error = RuntimeError(private_text)
    path = tmp_path / "unknown-r11.jsonl"
    store = r11_tool.build_r11_store(path)
    deferred = r11_tool.DeferredR11PreviewRestClient(
        store=store,
        prepared_client=r11_tool.FuturesPreviewOnlyRestClient(delegate),
    )
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING),
    )
    producer = r11_tool.build_r11_producer(
        rest_client=deferred,
        store=store,
        now=lambda: NOW,
        correlation_id_factory=lambda: (
            "419cb4b8-b99d-4663-baa8-da9db777e611"
        ),
        idempotency_key_factory=lambda: (
            "ab47c508-d834-44bc-9732-138cf6077118"
        ),
    )

    with pytest.raises(FuturesOrderPreviewArtifactError, match="unknown"):
        producer.run()

    terminal = store.read_completed()
    assert terminal["status"] == terminal["outcome"] == "unknown"
    assert terminal["blocker"] == "preview_order_unknown_consumed"
    persisted = path.read_text(encoding="utf-8")
    assert private_text not in persisted
    assert "RuntimeError" not in persisted
    assert len(delegate.preview_calls) == 1
    AdminFuturesOrderPreviewResponse.model_validate(terminal)
    with pytest.raises(FuturesOrderPreviewArtifactError, match="already consumed"):
        producer.run()
    assert len(delegate.preview_calls) == 1


def test_r11_claim_reservation_failure_is_value_blind_and_claim_only_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_text = "PRIVATE-R11-RESERVATION-FSYNC-TEXT"
    delegate = _r8_compatible_rest_client()
    initial_read_calls = list(delegate.read_calls)
    path = tmp_path / "reservation-failed-r11.jsonl"
    store = r11_tool.build_r11_store(path)
    deferred = r11_tool.DeferredR11PreviewRestClient(
        store=store,
        prepared_client=r11_tool.FuturesPreviewOnlyRestClient(delegate),
    )
    producer = r11_tool.build_r11_producer(
        rest_client=deferred,
        store=store,
        now=lambda: NOW,
        correlation_id_factory=lambda: (
            "619cb4b8-b99d-4663-baa8-da9db777e611"
        ),
        idempotency_key_factory=lambda: (
            "cb47c508-d834-44bc-9732-138cf6077118"
        ),
    )

    def partial_reservation_then_fail(_claim: object) -> str:
        path.write_text("partial-sanitized-r11-claim\n", encoding="utf-8")
        raise OSError(private_text)

    monkeypatch.setattr(store, "reserve", partial_reservation_then_fail)

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="claim persistence unavailable; attempt consumed",
    ) as caught:
        producer.run()

    assert private_text not in str(caught.value)
    assert path.exists()
    assert delegate.read_calls == initial_read_calls
    assert delegate.preview_calls == []
    assert delegate.forbidden_calls == []


def test_r11_cli_catches_unexpected_claim_boundary_error_value_blind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_text = "PRIVATE-R11-CLI-CLAIM-BOUNDARY-TEXT"
    path = tmp_path / "cli-claim-failed-r11.jsonl"
    monkeypatch.setattr(r11_tool, "_R11_CLI_BOOTSTRAP_VALIDATED", True)
    monkeypatch.setattr(r11_tool, "R11_PREVIEW_CALL_AUTHORITY_ACTIVE", True)
    monkeypatch.setattr(r11_tool, "R11_FINAL_AUDIT_BINDING_READY", True)
    monkeypatch.setattr(r11_tool, "production_artifact_path", lambda: path)
    monkeypatch.setattr(r11_tool, "_validate_final_audit_binding", lambda: None)
    monkeypatch.setattr(r11_tool, "_validate_sdk_pin", lambda: None)
    monkeypatch.setattr(r11_tool, "_validate_fresh_claim_contract", lambda _path: None)
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING),
    )

    class FailingProducer:
        def run(self) -> dict[str, object]:
            path.write_text("partial-sanitized-r11-claim\n", encoding="utf-8")
            raise OSError(private_text)

    monkeypatch.setattr(
        r11_tool,
        "build_r11_producer",
        lambda **_kwargs: FailingProducer(),
    )
    monkeypatch.setattr(
        r11_tool,
        "_build_r11_preview_rest_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("credential hydration must remain deferred")
        ),
    )

    assert r11_tool.main(["--confirm-one-r11-preview"]) == 2

    captured = capsys.readouterr()
    assert private_text not in captured.out
    assert private_text not in captured.err
    summary = json.loads(captured.err)
    assert summary["status"] == summary["outcome"] == "unknown"
    assert summary["blocker"] == "futures_preview_r11_consumed_without_terminal"
    assert summary["artifact_created"] is True
    assert summary["attempt_counters"] is None
    assert summary["exchange_submission_attempt_count"] == 0


@pytest.mark.parametrize("preview_outcome", ["accepted", "unknown"])
def test_r11_terminal_append_failure_keeps_claim_consumed_without_second_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preview_outcome: str,
) -> None:
    private_text = "PRIVATE-R11-TERMINAL-APPEND-TEXT"
    delegate = _r8_compatible_rest_client()
    if preview_outcome == "accepted":
        delegate.preview_response["is_max"] = False
    else:
        delegate.preview_error = RuntimeError("PRIVATE-R11-TRANSPORT-TEXT")
    path = tmp_path / f"append-failed-{preview_outcome}-r11.jsonl"
    store = r11_tool.build_r11_store(path)
    deferred = r11_tool.DeferredR11PreviewRestClient(
        store=store,
        prepared_client=r11_tool.FuturesPreviewOnlyRestClient(delegate),
    )
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING),
    )
    producer = r11_tool.build_r11_producer(
        rest_client=deferred,
        store=store,
        now=lambda: NOW,
        correlation_id_factory=lambda: (
            "519cb4b8-b99d-4663-baa8-da9db777e611"
        ),
        idempotency_key_factory=lambda: (
            "bb47c508-d834-44bc-9732-138cf6077118"
        ),
    )
    append_attempts = 0

    def failed_append(_result: object) -> None:
        nonlocal append_attempts
        append_attempts += 1
        raise RuntimeError(private_text)

    monkeypatch.setattr(store, "append_result", failed_append)

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="terminal persistence unavailable; attempt consumed",
    ):
        producer.run()

    assert append_attempts == 1
    assert len(delegate.preview_calls) == 1
    rows = store._read_rows()  # noqa: SLF001
    assert len(rows) == 1
    assert rows[0]["record_type"] == "claim"
    persisted = path.read_text(encoding="utf-8")
    assert private_text not in persisted
    assert "PRIVATE-R11-TRANSPORT-TEXT" not in persisted
    with pytest.raises(FuturesOrderPreviewArtifactError, match="already consumed"):
        producer.run()
    assert append_attempts == 1
    assert len(delegate.preview_calls) == 1


def test_r11_fixed_builders_cannot_redirect_predecessor_artifact_type_or_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "r11-claim.jsonl"
    store = r11_tool.build_r11_store(path)
    monkeypatch.setattr(
        r11_tool,
        "validate_production_predecessor",
        lambda: dict(preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING),
    )
    producer = r11_tool.build_r11_producer(rest_client=object(), store=store)

    claim = producer.build_claim()

    assert store.path == path
    assert claim["artifact_type"] == (
        preview_module.FUTURES_PREVIEW_R11_ARTIFACT_TYPE
    )
    assert claim["predecessor_binding"] == (
        preview_module.FUTURES_PREVIEW_R10_TERMINAL_BINDING
    )
    preview_module._validate_r11_ephemeral_claim_record(claim)
    assert r11_tool.production_artifact_path() == (
        preview_module.FUTURES_PREVIEW_R11_ARTIFACT_PATH
    )
