import json
from pathlib import Path

import pytest

from tools.check_runtime_artifacts import (
    SUMMARY_PREFIX,
    find_runtime_artifacts,
    main,
)


pytestmark = pytest.mark.regression


def test_runtime_artifact_checker_reports_admin_api_contract_artifacts(tmp_path):
    runtime_state = tmp_path / "runtime_state"
    response_dir = (
        runtime_state
        / "test_admin_api_contract"
        / "store-001"
        / "idempotency_responses"
    )
    response_dir.mkdir(parents=True)
    (response_dir / "response.json.gz").write_bytes(b"x" * 64)

    findings = find_runtime_artifacts(runtime_state, min_bytes=1)

    assert len(findings) == 1
    assert findings[0].path == runtime_state / "test_admin_api_contract"
    assert findings[0].reason == "admin_api_contract_runtime_state"
    assert findings[0].total_bytes == 64
    assert findings[0].largest_file_bytes == 64


def test_runtime_artifact_checker_reports_standalone_response_blobs(tmp_path):
    runtime_state = tmp_path / "runtime_state"
    response_dir = runtime_state / "admin_api_idempotency_responses"
    response_dir.mkdir(parents=True)
    (response_dir / "response.json.gz").write_bytes(b"x" * 32)

    findings = find_runtime_artifacts(runtime_state, min_bytes=1)

    assert len(findings) == 1
    assert findings[0].path == response_dir
    assert findings[0].reason == "idempotency_response_blobs"
    assert findings[0].total_bytes == 32


def test_runtime_artifact_checker_is_report_only_by_default(tmp_path, capsys):
    runtime_state = tmp_path / "runtime_state"
    artifact_dir = runtime_state / "pytest_full_probe"
    artifact_dir.mkdir(parents=True)
    artifact_file = artifact_dir / "result.log"
    artifact_file.write_bytes(b"x" * 32)

    exit_code = main(
        [
            "--runtime-state-dir",
            str(runtime_state),
            "--min-artifact-mb",
            "0.000001",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert artifact_file.exists()
    assert "Report-only: no files were deleted." in captured.out
    summary = next(
        line for line in captured.out.splitlines() if line.startswith(SUMMARY_PREFIX)
    )
    payload = json.loads(summary.removeprefix(SUMMARY_PREFIX))
    assert payload["status"] == "artifacts_found"
    assert payload["artifact_count"] == 1
    assert payload["live_coinbase_execution"] is False
    assert payload["live_coinbase_notional_usdc"] == "0"


def test_runtime_artifact_checker_can_fail_on_explicit_cap(tmp_path, capsys):
    runtime_state = tmp_path / "runtime_state"
    artifact_dir = runtime_state / "test_admin_api_contract"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "payload.bin").write_bytes(b"x" * 128)

    exit_code = main(
        [
            "--runtime-state-dir",
            str(runtime_state),
            "--min-artifact-mb",
            "0",
            "--fail-above-gb",
            "0.000000001",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out.startswith(SUMMARY_PREFIX)
    payload = json.loads(captured.out.removeprefix(SUMMARY_PREFIX))
    assert payload["status"] == "artifact_limit_exceeded"
    assert payload["total_bytes"] == 128


def test_runtime_artifact_summary_prefix_is_machine_readable_contract():
    assert SUMMARY_PREFIX == "RUNTIME_ARTIFACT_SUMMARY "
