"""Regression contracts for non-destructive deployment automation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.enums import EngineState
from scripts.runtime_healthcheck import summarize_status, validate_paused_status


pytestmark = pytest.mark.regression

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = PROJECT_ROOT / "scripts" / "validate_release.sh"
DEPLOY_SCRIPT = PROJECT_ROOT / "scripts" / "deploy_runtime.sh"
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "scripts" / "bootstrap_runtime_database.sh"
HEALTHCHECK_SCRIPT = PROJECT_ROOT / "scripts" / "runtime_healthcheck.py"


def _paused_payload(**overrides):
    payload = {
        "type": "admin_status_response",
        "engine_state": EngineState.PAUSED.value,
        "is_admitting": False,
        "is_stopping": False,
        "startup_pause_pending": False,
        "inflight": {},
        "total_inflight": 0,
    }
    payload.update(overrides)
    return payload


def test_deployment_scripts_have_valid_entrypoint_help_and_syntax():
    for script in (RELEASE_SCRIPT, DEPLOY_SCRIPT, BOOTSTRAP_SCRIPT):
        syntax = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert syntax.returncode == 0, syntax.stderr

        help_result = subprocess.run(
            [str(script), "--help"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stderr
        assert "Usage:" in help_result.stdout

    health_help = subprocess.run(
        [sys.executable, str(HEALTHCHECK_SCRIPT), "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert health_help.returncode == 0, health_help.stderr
    assert "stable PAUSED health" in health_help.stdout


def test_release_validation_uses_canonical_non_external_gate():
    source = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert '"${project_root}/scripts/run_tests.sh"' in source
    assert '"${project_root}/codex_repo_graph/build_graph.py" --check' in source
    assert "git diff --check" in source
    assert "git status --porcelain=v1 --untracked-files=all" in source
    assert "git push" not in source
    assert "external/" not in source


def test_runtime_deployment_reuses_canonical_paths_and_stays_foreground():
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert 'cd "${project_root}"' in source
    assert '"${project_root}/scripts/validate_release.sh"' in source
    assert '"${project_root}/scripts/bootstrap_runtime_database.sh"' in source
    assert '"${python_bin}" -m main &' in source
    assert 'wait "${engine_pid}"' in source
    assert "ENGINE_START_PAUSED=true" in source
    assert "DISABLE_RECONCILER" in source
    assert "runtime_healthcheck.py" in source
    assert source.count("assert_no_running_dashboard") >= 3
    assert "__dangerous_delete_all_tables__" not in source
    assert "admin_resume" not in source
    assert "git push" not in source
    assert "nohup" not in source
    assert "--confirm-target" not in source

    bootstrap_source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert 'cd "${project_root}"' in bootstrap_source


def test_paused_health_requires_closed_admission_and_no_inflight_work():
    status = validate_paused_status(_paused_payload())

    assert status == {
        "engine_state": EngineState.PAUSED.value,
        "is_admitting": False,
        "is_stopping": False,
        "startup_pause_pending": False,
        "total_inflight": 0,
    }


@pytest.mark.parametrize(
    "override",
    (
        {"engine_state": EngineState.RUNNING.value},
        {"is_admitting": True},
        {"is_stopping": True},
        {"startup_pause_pending": True},
        {"total_inflight": 1},
    ),
)
def test_paused_health_rejects_unsafe_runtime_state(override):
    with pytest.raises(RuntimeError):
        validate_paused_status(_paused_payload(**override))


def test_status_probe_reports_state_without_opening_admission():
    payload = _paused_payload(engine_state=EngineState.STARTING.value)

    assert summarize_status(json.loads(json.dumps(payload))) == {
        "engine_state": EngineState.STARTING.value,
        "is_admitting": False,
        "is_stopping": False,
        "startup_pause_pending": False,
        "total_inflight": 0,
    }
