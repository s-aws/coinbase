import json
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

from tools import run_admin_api_controlled_live_mvp_smoke as controlled_live_smoke
from tools import apply_admin_api_local_deployment as local_deployment
from tools import write_admin_api_deployment_manifest as deployment_manifest


DEPLOY_WORKFLOW_PATH = Path(".github/workflows/deploy.yml")
PUBLIC_CHECKS_WORKFLOW_PATH = Path(".github/workflows/public-agent-checks.yml")
GITIGNORE_PATH = Path(".gitignore")
PYPROJECT_PATH = Path("pyproject.toml")
TEST_REQUIREMENTS_PATH = Path("tests/requirements.txt")
OPENAPI_GENERATOR_PATH = Path("tools/generate_admin_api_openapi.py")
ROUTE_INVENTORY_EXPORTER_PATH = Path("tools/export_admin_api_route_inventory.py")
CONTROLLED_LIVE_SMOKE_RUNNER_PATH = Path(
    "tools/run_admin_api_controlled_live_mvp_smoke.py"
)
CONTROLLED_LIVE_SMOKE_TIMING_PATH = (
    "artifacts/coinbase-backend-controlled-live-mvp-smoke-timing.json"
)
LOCAL_DEPLOYMENT_MANIFEST_PATH = (
    "artifacts/coinbase-backend-local-deployment-manifest.json"
)


def test_backend_continuous_deployment_workflow_exists() -> None:
    assert DEPLOY_WORKFLOW_PATH.exists(), "backend continuous deployment workflow is missing"


def test_public_agent_checks_workflow_is_manual_only() -> None:
    workflow = PUBLIC_CHECKS_WORKFLOW_PATH.read_text(encoding="utf-8")
    trigger_block = workflow.split("\njobs:", maxsplit=1)[0]

    assert "workflow_dispatch:" in trigger_block
    assert "pull_request:" not in trigger_block
    assert "push:" not in trigger_block


def test_backend_continuous_deployment_workflow_guards_local_deploy() -> None:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    normalized_workflow = workflow.replace(r"\"", '"')

    for expected_text in [
        "name: Continuous Deployment",
        "workflow_run:",
        "Public Agent Checks",
        "workflow_dispatch:",
        "deploy-local:",
        "COINBASE_BACKEND_DEPLOYMENT_TIER: local",
        "COINBASE_BACKEND_LOCAL_DEPLOY_ROOT",
        "coinbase-local/backend",
        "python tools/check_ownership.py",
        "python tools/run_autonomous_work_queue_check.py --summary-only",
        "python tools/generate_admin_api_openapi.py --check",
        "python tools/export_admin_api_route_inventory.py --check",
        "python -m pytest tests/regression/test_admin_api_local_run_contract.py -v --tb=short",
        "Admin API controlled-live MVP route smoke",
        "python tools/run_admin_api_controlled_live_mvp_smoke.py",
        CONTROLLED_LIVE_SMOKE_TIMING_PATH,
        "python tools/run_admin_oidc_readiness_smoke.py --summary-only",
        "python tools/write_admin_api_deployment_manifest.py --deployment-tier local",
        "python -m compileall -q -b",
        "find \\",
        "-name '*.pyc'",
        "-delete",
        "python tools/apply_admin_api_local_deployment.py",
        "coinbase-backend-deployment.tgz",
        "artifacts/coinbase-backend-deployment-manifest.json",
        CONTROLLED_LIVE_SMOKE_TIMING_PATH,
        LOCAL_DEPLOYMENT_MANIFEST_PATH,
        "coinbase-local/backend/current-release.json",
        "python-version: \"3.13\"",
        "python -m pip install -e \".[test]\"",
        "Live Coinbase execution: not run; notional $0",
    ]:
        assert expected_text in normalized_workflow

    for forbidden_text in [
        "deployments: write",
        "environment: staging",
        "COINBASE_BACKEND_DEPLOY_WEBHOOK_URL",
        "Validate deploy hook",
        "Write backend deployment webhook payload",
        "Call deployment webhook",
        "curl --fail",
        "deployment-webhook-payload",
        "-d @",
    ]:
        assert forbidden_text not in normalized_workflow


def test_backend_continuous_deployment_workflow_only_runs_after_success() -> None:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "cancel-in-progress: false" in workflow


def test_backend_deploy_applies_local_target_before_uploading_payload() -> None:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.index("Apply local backend deployment") > workflow.index(
        "Package backend deploy payload"
    )
    assert workflow.index("Upload deployment payload") > workflow.index(
        "Apply local backend deployment"
    )
    assert workflow.index("Confirm local no-live posture") > workflow.index(
        "Apply local backend deployment"
    )


def test_backend_deploy_runs_controlled_live_mvp_smoke_before_packaging() -> None:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.index("Admin API controlled-live MVP route smoke") > workflow.index(
        "Admin API deploy smoke"
    )
    assert workflow.index("Package backend deploy payload") > workflow.index(
        "Admin API controlled-live MVP route smoke"
    )
    assert workflow.index(CONTROLLED_LIVE_SMOKE_TIMING_PATH) < workflow.index(
        "Package backend deploy payload"
    )
    assert workflow.index("Upload deployment payload") > workflow.index(
        CONTROLLED_LIVE_SMOKE_TIMING_PATH
    )


def test_backend_generated_artifacts_are_gitignored() -> None:
    gitignore = GITIGNORE_PATH.read_text(encoding="utf-8")

    assert "/artifacts/" in gitignore
    result = subprocess.run(
        ["git", "check-ignore", "-q", CONTROLLED_LIVE_SMOKE_TIMING_PATH],
        check=False,
    )
    assert result.returncode == 0


def test_backend_deploy_payload_contains_admin_runtime_contract_files() -> None:
    payload_block = _deploy_payload_block()

    for expected_path in [
        "artifacts/coinbase-backend-deployment-manifest.json",
        "products.json",
        "openapi/coinbase-admin-api.yaml",
        "openapi/coinbase-admin-api-route-inventory.json",
        "pyproject.toml",
        "tools/run_admin_api.py",
        "tools/write_admin_api_deployment_manifest.py",
        "tools/apply_admin_api_local_deployment.py",
        "tools/export_admin_api_route_inventory.py",
        "tools/run_admin_api_controlled_live_mvp_smoke.py",
        "tools/run_admin_api_futures_live_fill_readback.py",
        "tools/run_admin_api_manual_order_live_submit.py",
        "tools/run_admin_api_usdc_pair_snapshot_live_submit.py",
        "tools/run_admin_api_usdc_pair_snapshot_live_readback.py",
        "tools/coinbase_live_credentials.py",
        "tools/run_spot_fill_backfill_recovery.py",
        "tools/run_spot_sweep_recovery_gate.py",
        CONTROLLED_LIVE_SMOKE_TIMING_PATH,
        "logging_service.py",
    ]:
        assert expected_path in payload_block


def test_backend_deployment_manifest_describes_admin_runtime_without_live_execution() -> None:
    manifest = deployment_manifest.build_deployment_manifest(
        generated_at="2026-07-01T00:00:00Z",
        commit="abc123",
        deployment_tier="local",
    )

    assert manifest["schema_version"] == "1"
    assert manifest["artifact_type"] == "coinbase_admin_api_deployment_manifest"
    assert manifest["deployment_tier"] == "local"
    assert manifest["commit"] == "abc123"
    assert manifest["runtime"]["app"] == "api.v1.app:app"
    assert manifest["runtime"]["python_version"] == "3.13"
    assert manifest["runtime"]["requires_python"] == ">=3.13"
    assert manifest["runtime"]["dependency_manifest"] == "pyproject.toml"
    assert manifest["runtime"]["install_command"] == "python -m pip install ."
    assert manifest["runtime"]["environment_env"] == "COINBASE_ADMIN_API_ENVIRONMENT"
    assert manifest["runtime"]["deployment_tier_env"] == "COINBASE_BACKEND_DEPLOYMENT_TIER"
    assert manifest["runtime"]["default_environment"] == "local"
    assert manifest["runtime"]["start_command"] == (
        "python tools/run_admin_api.py --host 0.0.0.0 --port 8787"
    )
    assert manifest["runtime"]["health_check"] == "GET /api/v1/admin/health"
    assert manifest["auth"]["production_mode"] == "oidc_jwt"
    assert "COINBASE_ADMIN_API_BEARER_TOKEN" in manifest["auth"]["bootstrap_env"]
    assert "COINBASE_ADMIN_API_OIDC_JWKS_URL" in manifest["auth"]["oidc_env"]
    assert manifest["live_coinbase_execution"] == "not_run"
    assert manifest["notional_usdc"] == "0"
    assert manifest["frontend_authority"] == "operator_ui_only"
    assert manifest["live_action_path"] == "auditable_backend_admin_interfaces_only"
    assert manifest["verification"]["controlled_live_mvp_smoke"] == {
        "command": "python tools/run_admin_api_controlled_live_mvp_smoke.py",
        "timing_artifact": CONTROLLED_LIVE_SMOKE_TIMING_PATH,
        "summary_prefix": "ADMIN_API_CONTROLLED_LIVE_MVP_SMOKE_SUMMARY",
        "required_status": "passed",
        "wait_sleep_seconds_field": "wait_sleep_seconds",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
    }


def test_backend_deployment_manifest_prefers_ci_deployment_ref(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_REF", "ci-deploy-ref")
    monkeypatch.setenv("GITHUB_SHA", "github-sha")

    args = deployment_manifest.build_parser().parse_args([])

    assert args.commit == "ci-deploy-ref"


def test_public_agent_checks_cover_backend_continuous_deployment_contract() -> None:
    workflow = PUBLIC_CHECKS_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Enable Windows long paths" in workflow
    assert "git config --global core.longpaths true" in workflow
    assert workflow.index("Enable Windows long paths") < workflow.index("uses: actions/checkout@v4")
    assert "python -m pytest tests/regression/test_backend_cd_workflow.py -v --tb=short" in workflow
    assert "python tools/generate_admin_api_openapi.py --check" in workflow
    assert "python tools/export_admin_api_route_inventory.py --check" in workflow
    assert "Admin API controlled-live MVP route smoke" in workflow
    assert "python tools/run_admin_api_controlled_live_mvp_smoke.py --summary-only" in workflow


def test_controlled_live_mvp_smoke_runner_records_timing_summary() -> None:
    assert CONTROLLED_LIVE_SMOKE_RUNNER_PATH.exists()
    runner = CONTROLLED_LIVE_SMOKE_RUNNER_PATH.read_text(encoding="utf-8")

    assert "ADMIN_API_CONTROLLED_LIVE_MVP_SMOKE_SUMMARY" in runner
    assert "coinbase_admin_api_controlled_live_mvp_smoke_timing" in runner
    assert "wait_sleep_seconds" in runner
    assert "backend_git_commit" in runner
    assert "backend_contract_ref" in runner
    assert CONTROLLED_LIVE_SMOKE_TIMING_PATH in runner

    command = controlled_live_smoke.build_pytest_command()
    assert command[:3] == [controlled_live_smoke.sys.executable, "-m", "pytest"]
    for nodeid in [
        "test_admin_api_order_live_execution_service_dependency_reads_decision_log",
        "test_read_surfaces_expose_controlled_live_manual_order_from_backend_decision",
        "test_admin_api_manual_order_route_passes_backend_admission_to_command_service",
        "test_admin_api_manual_order_route_executes_through_backend_runtime_dependencies",
        "test_admin_api_manual_order_route_blocks_admitted_quote_above_backend_cap",
    ]:
        assert any(nodeid in part for part in command)

    summary = controlled_live_smoke.build_timing_summary(
        result=controlled_live_smoke.SmokeRunResult(
            return_code=0,
            started_at="2026-07-01T00:00:00Z",
            ended_at="2026-07-01T00:00:12Z",
            duration_seconds=12.0,
        ),
        command=command,
        backend_git=controlled_live_smoke.BackendGitEvidence(
            commit="backendabc",
            branch="codex/mvp",
        ),
        backend_contract_ref="backendabc",
    )
    assert summary["artifact_type"] == "coinbase_admin_api_controlled_live_mvp_smoke_timing"
    assert summary["status"] == "passed"
    assert summary["duration_seconds"] == 12.0
    assert summary["wait_sleep_seconds"] == 0.0
    assert summary["backend_git_commit"] == "backendabc"
    assert summary["backend_git_branch"] == "codex/mvp"
    assert summary["backend_contract_ref"] == "backendabc"
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["notional_usdc"] == "0"


def test_backend_local_deployment_manifest_includes_smoke_timing() -> None:
    deploy_root = Path("coinbase-local/backend").resolve()

    payload = local_deployment.build_local_deployment_manifest(
        repository="s-aws/coinbase",
        commit="abc123",
        deployment_tier="local",
        target_name="coinbase-local-backend",
        deploy_root=deploy_root,
        current_path=deploy_root / "current",
        release_path=deploy_root / "releases" / "abc123",
        smoke_timing=_passed_smoke_timing(),
        generated_at="2026-07-01T00:00:00Z",
    )

    assert payload["schema_version"] == "1"
    assert payload["artifact_type"] == "coinbase_admin_api_local_deployment_manifest"
    assert payload["repository"] == "s-aws/coinbase"
    assert payload["commit"] == "abc123"
    assert payload["environment"] == "local"
    assert payload["deployment_tier"] == "local"
    assert payload["target_name"] == "coinbase-local-backend"
    assert payload["deploy_root"] == str(deploy_root)
    assert payload["current_path"] == str(deploy_root / "current")
    assert payload["release_path"] == str(deploy_root / "releases" / "abc123")
    assert payload["artifact"] == "coinbase-backend-deployment.tgz"
    assert payload["manifest"] == "coinbase-backend-deployment-manifest.json"
    assert payload["smoke_timing_artifact"] == (
        "coinbase-backend-controlled-live-mvp-smoke-timing.json"
    )
    assert payload["smoke_timing_summary"] == (
        "ADMIN_API_CONTROLLED_LIVE_MVP_SMOKE_SUMMARY"
    )
    assert payload["smoke_timing"] == {
        "status": "passed",
        "duration_seconds": 12.345,
        "wait_sleep_seconds": 0.0,
        "backend_git_commit": "backendabc",
        "backend_git_branch": "codex/mvp",
        "backend_contract_ref": "backendabc",
        "command": ["python", "-m", "pytest"],
        "smoke_node_count": len(controlled_live_smoke.SMOKE_NODE_IDS),
        "smoke_node_ids": list(controlled_live_smoke.SMOKE_NODE_IDS),
    }
    assert payload["live_coinbase_execution"] == "not_run"
    assert payload["notional_usdc"] == "0"


def test_backend_local_deployment_rejects_failed_smoke_timing() -> None:
    with pytest.raises(ValueError, match="status passed"):
        local_deployment.build_local_deployment_manifest(
            repository="s-aws/coinbase",
            commit="abc123",
            deployment_tier="local",
            target_name="coinbase-local-backend",
            deploy_root=Path("coinbase-local/backend"),
            current_path=Path("coinbase-local/backend/current"),
            release_path=Path("coinbase-local/backend/releases/abc123"),
            smoke_timing=_passed_smoke_timing(status="failed", return_code=1),
            generated_at="2026-07-01T00:00:00Z",
        )


def test_backend_local_deployment_reads_powershell_utf8_bom(
    tmp_path: Path,
) -> None:
    timing_path = tmp_path / "smoke-timing.json"
    timing_path.write_text(
        (
            '{"status":"passed","duration_seconds":12.345,'
            '"wait_sleep_seconds":0.0,'
            '"backend_git_commit":"backendabc",'
            '"backend_git_branch":"codex/mvp",'
            '"backend_contract_ref":"backendabc",'
            '"command":["python"],'
            f'"smoke_node_ids":{json.dumps(list(controlled_live_smoke.SMOKE_NODE_IDS))},'
            '"live_coinbase_execution":"not_run","notional_usdc":"0"}'
        ),
        encoding="utf-8-sig",
    )

    payload = local_deployment.build_local_deployment_manifest(
        repository="s-aws/coinbase",
        commit="abc123",
        deployment_tier="local",
        target_name="coinbase-local-backend",
        deploy_root=tmp_path / "coinbase-local" / "backend",
        current_path=tmp_path / "coinbase-local" / "backend" / "current",
        release_path=tmp_path / "coinbase-local" / "backend" / "releases" / "abc123",
        smoke_timing=local_deployment.read_json(timing_path),
        generated_at="2026-07-01T00:00:00Z",
    )

    assert payload["smoke_timing"]["duration_seconds"] == 12.345
    assert payload["smoke_timing"]["backend_contract_ref"] == "backendabc"
    assert payload["smoke_timing"]["smoke_node_ids"] == list(
        controlled_live_smoke.SMOKE_NODE_IDS
    )
    assert payload["live_coinbase_execution"] == "not_run"
    assert payload["notional_usdc"] == "0"


def test_backend_local_deployment_rejects_missing_smoke_nodes() -> None:
    smoke_node_ids = list(controlled_live_smoke.SMOKE_NODE_IDS)
    smoke_node_ids.remove(
        "tests/regression/test_admin_api_contract.py::"
        "test_read_surfaces_expose_controlled_live_manual_order_from_backend_decision"
    )

    with pytest.raises(ValueError, match="required smoke nodes"):
        local_deployment.build_local_deployment_manifest(
            repository="s-aws/coinbase",
            commit="abc123",
            deployment_tier="local",
            target_name="coinbase-local-backend",
            deploy_root=Path("coinbase-local/backend"),
            current_path=Path("coinbase-local/backend/current"),
            release_path=Path("coinbase-local/backend/releases/abc123"),
            smoke_timing=_passed_smoke_timing(smoke_node_ids=smoke_node_ids),
            generated_at="2026-07-01T00:00:00Z",
        )


def test_backend_local_deployment_defaults_to_local_git_commit(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEPLOYMENT_REF", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("COINBASE_BACKEND_DEPLOYMENT_TIER", raising=False)
    expected_commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        text=True,
    ).strip()

    args = local_deployment.build_parser().parse_args([])

    assert local_deployment.read_git_commit() == expected_commit
    assert args.commit == expected_commit
    assert args.deployment_tier == "local"


def test_backend_local_deployment_prefers_ci_deployment_ref(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEPLOYMENT_REF", "ci-deploy-ref")
    monkeypatch.setenv("GITHUB_SHA", "github-sha")
    monkeypatch.delenv("COINBASE_BACKEND_DEPLOYMENT_TIER", raising=False)

    args = local_deployment.build_parser().parse_args([])

    assert args.commit == "ci-deploy-ref"


def test_backend_local_deployment_rejects_manifest_commit_mismatch(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    local_deployment.write_json(
        manifest_path,
        {
            "artifact_type": "coinbase_admin_api_deployment_manifest",
            "commit": "manifest-commit",
            "deployment_tier": "local",
            "live_coinbase_execution": "not_run",
            "notional_usdc": "0",
        },
    )

    with pytest.raises(ValueError, match="deployment manifest"):
        local_deployment.assert_deployment_manifest(
            manifest_path,
            "payload-commit",
            "local",
        )


def test_backend_local_deployment_rejects_live_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    local_deployment.write_json(
        manifest_path,
        {
            "artifact_type": "coinbase_admin_api_deployment_manifest",
            "commit": "payload-commit",
            "deployment_tier": "local",
            "live_coinbase_execution": "ran",
            "notional_usdc": "1",
        },
    )

    with pytest.raises(ValueError, match="live Coinbase execution"):
        local_deployment.assert_deployment_manifest(
            manifest_path,
            "payload-commit",
            "local",
        )


def test_backend_local_deployment_rejects_non_local_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    local_deployment.write_json(
        manifest_path,
        {
            "artifact_type": "coinbase_admin_api_deployment_manifest",
            "commit": "payload-commit",
            "deployment_tier": "staging",
            "live_coinbase_execution": "not_run",
            "notional_usdc": "0",
        },
    )

    with pytest.raises(ValueError, match="local deployment only"):
        local_deployment.assert_deployment_manifest(
            manifest_path,
            "payload-commit",
            "local",
        )


def test_backend_local_deployment_applies_archive_to_versioned_target(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source" / "README.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("admin api artifact\n", encoding="utf-8")
    archive_path = tmp_path / "coinbase-backend-deployment.tgz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        archive.add(source_path, arcname="README.md")

    manifest_path = tmp_path / "deployment-manifest.json"
    local_deployment.write_json(
        manifest_path,
        {
            "artifact_type": "coinbase_admin_api_deployment_manifest",
            "commit": "abc123",
            "deployment_tier": "local",
            "live_coinbase_execution": "not_run",
            "notional_usdc": "0",
        },
    )
    smoke_timing_path = tmp_path / "smoke-timing.json"
    local_deployment.write_json(smoke_timing_path, _passed_smoke_timing())

    deploy_root = tmp_path / "coinbase-local" / "backend"
    output_path = tmp_path / "local-deployment-manifest.json"
    manifest = local_deployment.apply_local_deployment(
        archive_path=archive_path,
        manifest_path=manifest_path,
        smoke_timing_path=smoke_timing_path,
        output_path=output_path,
        deploy_root=deploy_root,
        target_name="coinbase-local-backend",
        repository="s-aws/coinbase",
        commit="abc123",
        deployment_tier="local",
        generated_at="2026-07-01T00:00:00Z",
    )

    assert (deploy_root / "current" / "README.md").read_text(
        encoding="utf-8"
    ) == "admin api artifact\n"
    assert (deploy_root / "current-release.json").exists()
    assert output_path.exists()
    assert manifest["artifact_type"] == "coinbase_admin_api_local_deployment_manifest"
    assert manifest["live_coinbase_execution"] == "not_run"
    assert manifest["notional_usdc"] == "0"


def test_backend_local_deployment_rejects_archive_path_escape(
    tmp_path: Path,
) -> None:
    escape_source_path = tmp_path / "escape.txt"
    escape_source_path.write_text("escape\n", encoding="utf-8")
    archive_path = tmp_path / "bad.tgz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        archive.add(escape_source_path, arcname="../escape.txt")

    with pytest.raises(ValueError, match="outside the local release directory"):
        local_deployment.extract_archive_safely(
            archive_path,
            tmp_path / "coinbase-local" / "backend" / "releases" / "abc123",
        )


def test_backend_openapi_generator_supports_check_mode() -> None:
    generator = OPENAPI_GENERATOR_PATH.read_text(encoding="utf-8")

    assert "--check" in generator
    assert "Admin API OpenAPI schema is current" in generator


def test_backend_route_inventory_exporter_supports_check_mode() -> None:
    exporter = ROUTE_INVENTORY_EXPORTER_PATH.read_text(encoding="utf-8")

    assert "--check" in exporter
    assert "Admin API route inventory is current" in exporter


def test_backend_deploy_install_declares_admin_api_runtime_dependencies() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dependencies = _dependency_names(pyproject["project"]["dependencies"])
    test_dependencies = _dependency_names(
        pyproject["project"]["optional-dependencies"]["test"]
    )

    assert {
        "fastapi",
        "coinbase-advanced-py",
        "pydantic",
        "psycopg2-binary",
        "pyjwt",
        "pyyaml",
        "uvicorn",
    }.issubset(dependencies)
    assert {"httpx", "pytest", "pytest-timeout", "pytest-xdist"}.issubset(
        test_dependencies
    )


def test_legacy_test_requirements_include_pytest_startup_imports() -> None:
    requirements = _dependency_names(
        [
            line.strip()
            for line in TEST_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    )

    assert {"psycopg2-binary", "pyyaml"}.issubset(requirements)


def _passed_smoke_timing(**overrides: object) -> dict[str, object]:
    timing: dict[str, object] = {
        "schema_version": "1",
        "artifact_type": "coinbase_admin_api_controlled_live_mvp_smoke_timing",
        "status": "passed",
        "return_code": 0,
        "duration_seconds": 12.345,
        "wait_sleep_seconds": 0.0,
        "backend_git_commit": "backendabc",
        "backend_git_branch": "codex/mvp",
        "backend_contract_ref": "backendabc",
        "started_at": "2026-07-01T00:00:00Z",
        "ended_at": "2026-07-01T00:00:12Z",
        "command": ["python", "-m", "pytest"],
        "smoke_node_ids": list(controlled_live_smoke.SMOKE_NODE_IDS),
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
    }
    timing.update(overrides)
    return timing


def _dependency_names(requirements: list[str]) -> set[str]:
    names: set[str] = set()
    for requirement in requirements:
        name = requirement.split(";", 1)[0]
        for separator in ("[", "<", ">", "=", "~", "!"):
            name = name.split(separator, 1)[0]
        names.add(name.strip().lower())
    return names


def _deploy_payload_block() -> str:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    marker = "tar -czf artifacts/coinbase-backend-deployment.tgz"
    _, package_block = workflow.split(marker, 1)
    payload_lines: list[str] = []
    for line in package_block.splitlines():
        if not line.strip():
            break
        payload_lines.append(line)
    return "\n".join(payload_lines)
