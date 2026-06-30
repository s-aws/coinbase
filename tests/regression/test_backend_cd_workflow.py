from pathlib import Path
import tomllib


DEPLOY_WORKFLOW_PATH = Path(".github/workflows/deploy.yml")
PUBLIC_CHECKS_WORKFLOW_PATH = Path(".github/workflows/public-agent-checks.yml")
PYPROJECT_PATH = Path("pyproject.toml")


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


def test_public_agent_checks_cover_backend_continuous_deployment_contract() -> None:
    workflow = PUBLIC_CHECKS_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "python -m pytest tests/regression/test_backend_cd_workflow.py -v --tb=short" in workflow


def test_backend_deploy_install_declares_admin_api_runtime_dependencies() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dependencies = _dependency_names(pyproject["project"]["dependencies"])
    test_dependencies = _dependency_names(
        pyproject["project"]["optional-dependencies"]["test"]
    )

    assert {"fastapi", "pydantic", "pyjwt", "uvicorn"}.issubset(dependencies)
    assert {"httpx", "pytest", "pytest-timeout", "pytest-xdist"}.issubset(
        test_dependencies
    )


def _dependency_names(requirements: list[str]) -> set[str]:
    names: set[str] = set()
    for requirement in requirements:
        name = requirement.split(";", 1)[0]
        for separator in ("[", "<", ">", "=", "~", "!"):
            name = name.split(separator, 1)[0]
        names.add(name.strip().lower())
    return names
