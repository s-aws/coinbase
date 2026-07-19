"""Regression tests for the spot contextless-agent checklist harness."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.enums import SpotCampaignRunMode, SpotCampaignStatus
from tools.run_spot_contextless_agent_checklist import build_checklist, main


pytestmark = pytest.mark.regression


ROOT = Path(__file__).resolve().parents[2]


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
    assert (
        "four installed Controlled-live mutation routes: manual root "
        "place/cancel and explicit attached-intent materialization/exact-child "
        "safe-closeout"
    ) in checklist["pass_criteria"]


def test_contextless_agent_checklist_cli_summary_runs(capsys):
    assert main(["--summary-only"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("SPOT_CONTEXTLESS_AGENT_CHECKLIST ")
    assert "pass_criteria_count" in captured.out


@pytest.mark.parametrize(
    "relative_path",
    [
        "README.md",
        "README.admin-api.md",
        "README.spot-trading.md",
        "docs/EXTERNAL_TESTING_RUNBOOK.md",
        "docs/PUBLIC_RELEASE_READINESS.md",
        "docs/SPOT_READINESS_ROADMAP.md",
        "docs/SPOT_CONTEXTLESS_AGENT_TESTING.md",
        "docs/examples/spot-portfolio-sweep.md",
    ],
)
def test_current_operator_boundary_docs_name_all_four_controlled_live_routes(
    relative_path,
):
    text = (ROOT / relative_path).read_text(encoding="utf-8-sig")
    current_contract = " ".join(text.split()).lower()

    assert "four installed controlled-live mutation routes" in current_contract
    assert "manual root place/cancel" in current_contract
    assert "attached-intent materialization" in current_contract
    assert "exact-child safe-closeout" in current_contract

    current_intro = current_contract[:4000]
    assert "sole supported controlled-live operator surface" not in current_intro
    assert (
        "only supported controlled-live operator path is installed authenticated "
        "admin api manual spot limit/gtc place/cancel"
    ) not in current_intro
    assert "no-live is its safe default" not in current_intro


def test_current_operator_boundary_docs_drop_manual_only_runtime_claims():
    current_docs = " ".join(
        (ROOT / relative_path).read_text(encoding="utf-8-sig")
        for relative_path in (
            "README.admin-api.md",
            "README.spot-trading.md",
            "docs/PUBLIC_RELEASE_READINESS.md",
            "docs/SPOT_READINESS_ROADMAP.md",
            "docs/SPOT_CONTEXTLESS_AGENT_TESTING.md",
        )
    ).lower()
    normalized = " ".join(current_docs.split())

    for stale_claim in (
        "current controlled-live manual spot place/cancel",
        "supported controlled-live testing uses authenticated admin api manual spot place/cancel",
        "current controlled-live uses authenticated admin api manual spot place/cancel",
        "manual placement and spot cancel are route-scoped controlled-live capabilities",
        "controlled-live product ui must use the authenticated http admin api manual spot place/cancel contract",
        "runtime is armed and the two manual spot routes are supported",
        "contracts cannot mint manual place/cancel sdk scope or authorize coinbase mutation",
    ):
        assert stale_claim not in normalized
