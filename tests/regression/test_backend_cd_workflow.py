from pathlib import Path
import tomllib


DEPLOY_WORKFLOW_PATH = Path(".github/workflows/deploy.yml")
PUBLIC_CHECKS_WORKFLOW_PATH = Path(".github/workflows/public-agent-checks.yml")
PYPROJECT_PATH = Path("pyproject.toml")
TEST_REQUIREMENTS_PATH = Path("tests/requirements.txt")
OPENAPI_GENERATOR_PATH = Path("tools/generate_admin_api_openapi.py")
ROUTE_INVENTORY_EXPORTER_PATH = Path("tools/export_admin_api_route_inventory.py")


def test_backend_continuous_deployment_workflow_exists() -> None:
    assert DEPLOY_WORKFLOW_PATH.exists(), "backend continuous deployment workflow is missing"


def test_backend_continuous_deployment_workflow_guards_staging_deploy() -> None:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    normalized_workflow = workflow.replace(r"\"", '"')

    for expected_text in [
        "name: Continuous Deployment",
        "workflow_run:",
        "Public Agent Checks",
        "workflow_dispatch:",
        "environment: staging",
        "COINBASE_BACKEND_DEPLOY_WEBHOOK_URL",
        "python tools/check_ownership.py",
        "python tools/run_autonomous_work_queue_check.py --summary-only",
        "python tools/generate_admin_api_openapi.py --check",
        "python tools/export_admin_api_route_inventory.py --check",
        "python -m pytest tests/regression/test_admin_api_local_run_contract.py -v --tb=short",
        "python tools/run_admin_oidc_readiness_smoke.py --summary-only",
        "coinbase-backend-deployment.tgz",
        "Live Coinbase execution: not run; notional $0",
        '"liveCoinbaseExecution":"not_run"',
        '"notionalUsdc":"0"',
    ]:
        assert expected_text in normalized_workflow


def test_backend_continuous_deployment_workflow_only_runs_after_success() -> None:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "cancel-in-progress: false" in workflow


def test_backend_deploy_uploads_payload_before_calling_webhook() -> None:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.index("Upload deployment payload") > workflow.index(
        "Package backend deploy payload"
    )
    assert workflow.index("Call deployment webhook") > workflow.index(
        "Upload deployment payload"
    )


def test_backend_deploy_payload_contains_admin_runtime_contract_files() -> None:
    payload_block = _deploy_payload_block()

    for expected_path in [
        "products.json",
        "openapi/coinbase-admin-api.yaml",
        "openapi/coinbase-admin-api-route-inventory.json",
        "tools/export_admin_api_route_inventory.py",
    ]:
        assert expected_path in payload_block


def test_public_agent_checks_cover_backend_continuous_deployment_contract() -> None:
    workflow = PUBLIC_CHECKS_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "python -m pytest tests/regression/test_backend_cd_workflow.py -v --tb=short" in workflow
    assert "python tools/generate_admin_api_openapi.py --check" in workflow
    assert "python tools/export_admin_api_route_inventory.py --check" in workflow


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

    assert {"fastapi", "pydantic", "psycopg2-binary", "pyjwt", "uvicorn"}.issubset(
        dependencies
    )
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

    assert "psycopg2-binary" in requirements


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
