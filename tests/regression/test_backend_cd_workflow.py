from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/deploy.yml")


def test_backend_continuous_deployment_workflow_exists() -> None:
    assert WORKFLOW_PATH.exists(), "backend continuous deployment workflow is missing"


def test_backend_continuous_deployment_workflow_guards_staging_deploy() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
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
        "coinbase-backend-deployment.tgz",
        "Live Coinbase execution: not run; notional $0",
        '"liveCoinbaseExecution":"not_run"',
        '"notionalUsdc":"0"',
    ]:
        assert expected_text in normalized_workflow


def test_backend_continuous_deployment_workflow_only_runs_after_success() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "cancel-in-progress: false" in workflow
