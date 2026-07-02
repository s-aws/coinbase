from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools import run_admin_api_controlled_live_mvp_smoke as smoke


def test_controlled_live_mvp_smoke_writes_default_no_live_summary(
    monkeypatch,
    tmp_path: Path,
):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    monkeypatch.setattr(
        smoke,
        "read_git_value",
        lambda args, fallback="unknown": {
            ("rev-parse", "--short", "HEAD"): "abc1234",
            ("rev-parse", "--abbrev-ref", "HEAD"): "codex/prod-admin-mvp-local-cd",
        }.get(tuple(args), fallback),
    )
    summary_path = tmp_path / "controlled-live-smoke.json"

    exit_code = smoke.main(["--summary-output", str(summary_path)])

    assert exit_code == 0
    assert calls == [
        [
            smoke.resolve_python(),
            "-m",
            "pytest",
            *smoke.REQUIRED_BACKEND_CONTROLLED_LIVE_MVP_SMOKE_NODE_IDS,
            "-q",
            "--tb=short",
        ]
    ]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["artifact_type"] == (
        "coinbase_admin_api_controlled_live_mvp_smoke_timing"
    )
    assert summary["status"] == "passed"
    assert summary["backend_contract_ref"] == "abc1234"
    assert summary["backend_git_commit"] == "abc1234"
    assert summary["backend_git_branch"] == "codex/prod-admin-mvp-local-cd"
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["notional_usdc"] == "0"
    assert summary["wait_sleep_seconds"] == 0
    assert summary["return_code"] == 0
    assert summary["smoke_node_ids"] == (
        smoke.REQUIRED_BACKEND_CONTROLLED_LIVE_MVP_SMOKE_NODE_IDS
    )
    assert summary["duration_seconds"] >= 0


def test_controlled_live_mvp_smoke_marks_failed_pytest_run(
    monkeypatch,
    tmp_path: Path,
):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "failed")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    monkeypatch.setattr(smoke, "read_git_value", lambda args, fallback="unknown": "abc1234")
    summary_path = tmp_path / "controlled-live-smoke.json"

    exit_code = smoke.main(["--summary-output", str(summary_path)])

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert summary["status"] == "failed"
    assert summary["return_code"] == 1
    assert summary["live_coinbase_execution"] == "not_run"
    assert summary["notional_usdc"] == "0"
