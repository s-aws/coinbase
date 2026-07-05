from __future__ import annotations

import json
from pathlib import Path

from tools import apply_admin_api_local_deployment as local_deploy
from tools import write_admin_api_deployment_manifest as deployment_manifest


def test_backend_deployment_manifest_records_actual_run_outputs(tmp_path: Path):
    deploy_root = tmp_path / "coinbase-local" / "backend"

    manifest = deployment_manifest.build_deployment_manifest(
        generated_at="2026-07-02T00:00:00Z",
        repository="local",
        commit="abc123",
        branch="codex/prod-admin-mvp-local-cd",
        deployment_tier="local",
        deploy_root=deploy_root,
        target_name="coinbase-local-backend",
        live_coinbase_execution="submitted",
        notional_usdc="1.23",
    )

    assert manifest["artifact_type"] == "coinbase_admin_api_deployment_manifest"
    assert manifest["deployment_tier"] == "local"
    assert manifest["target_name"] == "coinbase-local-backend"
    assert manifest["runtime"]["default_port"] == 8787
    assert manifest["runtime"]["start_command"] == (
        "py -3.13 tools/run_admin_api.py --host 127.0.0.1 --port 8787 "
        "--dev-token local-admin-token"
    )
    assert manifest["frontend_authority"] == "operator_ui_only"
    assert manifest["live_action_path"] == "auditable_backend_admin_interfaces_only"
    assert manifest["live_coinbase_execution"] == "submitted"
    assert manifest["notional_usdc"] == "1.23"


def test_apply_backend_local_deployment_writes_current_release(tmp_path: Path):
    source_root = tmp_path / "source"
    deploy_root = tmp_path / "coinbase-local" / "backend"
    manifest_path = source_root / "artifacts" / "coinbase-backend-deployment-manifest.json"
    archive_path = source_root / "artifacts" / "coinbase-backend-deployment.tgz"
    _write_minimal_backend_source(source_root)
    manifest = deployment_manifest.build_deployment_manifest(
        generated_at="2026-07-02T00:00:00Z",
        repository="local",
        commit="abc123",
        branch="codex/prod-admin-mvp-local-cd",
        deployment_tier="local",
        deploy_root=deploy_root,
        target_name="coinbase-local-backend",
        live_coinbase_execution="not_run",
        notional_usdc="0",
    )
    deployment_manifest.write_json(manifest_path, manifest)

    local_manifest = local_deploy.apply_local_deployment(
        source_root=source_root,
        manifest_path=manifest_path,
        deploy_root=deploy_root,
        archive_path=archive_path,
    )

    current_manifest = json.loads(
        (deploy_root / "current-release.json").read_text(encoding="utf-8")
    )
    assert current_manifest == local_manifest
    assert current_manifest["artifact_type"] == (
        "coinbase_admin_api_local_deployment_manifest"
    )
    assert current_manifest["commit"] == "abc123"
    assert current_manifest["deployment_tier"] == "local"
    assert current_manifest["environment"] == "local"
    assert current_manifest["live_coinbase_execution"] == "not_run"
    assert current_manifest["notional_usdc"] == "0"
    assert Path(current_manifest["current_path"]) == deploy_root / "current"
    assert Path(current_manifest["release_path"]) == deploy_root / "releases" / "abc123"
    assert (deploy_root / "current" / "tools" / "run_admin_api.py").exists()
    assert (deploy_root / "current" / "api" / "v1" / "app.py").exists()
    assert (deploy_root / "current" / "logging_service.py").exists()
    assert (deploy_root / "current" / "tests" / "pytest.ini").exists()
    assert (
        deploy_root / "current" / "tests" / "regression" / "test_admin_api_contract.py"
    ).exists()
    assert (
        deploy_root / "current" / "tests" / "regression" / "test_admin_mvp_api.py"
    ).exists()
    assert not (deploy_root / "current" / "tools" / "__pycache__").exists()
    assert (
        deploy_root / "current" / "coinbase-backend-local-deployment-manifest.json"
    ).exists()
    assert archive_path.exists()


def _write_minimal_backend_source(source_root: Path) -> None:
    for relative_path in (
        "application/__init__.py",
        "application/admin_api/__init__.py",
        "application/admin_api/mvp_service.py",
        "api/__init__.py",
        "api/v1/__init__.py",
        "api/v1/app.py",
        "tools/__init__.py",
        "tools/run_admin_api.py",
        "logging_service.py",
        "tests/__init__.py",
        "tests/pytest.ini",
        "tests/conftest.py",
        "tests/regression/__init__.py",
        "tests/regression/test_admin_api_contract.py",
        "tests/regression/test_admin_mvp_api.py",
        "configuration.py",
        "dashboard_server.py",
        "pyproject.toml",
        "products.json",
        "README.md",
    ):
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative_path}\n", encoding="utf-8")
    pycache_path = source_root / "tools" / "__pycache__" / "run_admin_api.pyc"
    pycache_path.parent.mkdir(parents=True, exist_ok=True)
    pycache_path.write_bytes(b"compiled")
