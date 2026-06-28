"""Regression tests for the spot contextless-agent checklist harness."""

import subprocess
import sys
from datetime import datetime, timezone

import pytest

from core.enums import SpotCampaignRunMode, SpotCampaignStatus
from tools.run_spot_contextless_agent_checklist import build_checklist, main


pytestmark = pytest.mark.regression


def test_contextless_agent_checklist_is_read_only_and_prompt_complete():
    checklist = build_checklist(
        generated_at=datetime(2026, 6, 10, tzinfo=timezone.utc)
    )

    assert checklist["mode"] == SpotCampaignRunMode.CONTEXTLESS_AGENT_CHECKLIST.value
    assert checklist["status"] == SpotCampaignStatus.RECORDED.value
    assert checklist["source_doc"] == "docs/SPOT_CONTEXTLESS_AGENT_TESTING.md"
    assert "determine how a spot order is created" in checklist["blind_prompt"]
    assert len(checklist["pass_criteria"]) >= 10
    assert checklist["live_coinbase_orders_ran"] is False
    assert checklist["total_submitted_notional_usdc"] == "0"


def test_contextless_agent_checklist_cli_summary_runs(capsys):
    assert main(["--summary-only"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("SPOT_CONTEXTLESS_AGENT_CHECKLIST ")
    assert "pass_criteria_count" in captured.out


def test_contextless_agent_checklist_direct_script_uses_repo_imports():
    result = subprocess.run(
        [
            sys.executable,
            "tools/run_spot_contextless_agent_checklist.py",
            "--summary-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("SPOT_CONTEXTLESS_AGENT_CHECKLIST ")
    assert "contextless_agent_checklist" in result.stdout
