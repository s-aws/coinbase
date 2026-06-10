"""Print the repeatable contextless-agent spot order checklist.

The tool is intentionally read-only. It gives an operator the same blind prompt
and pass criteria every time so documentation fixes are made in the repository
instead of by coaching the agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.enums import SpotCampaignRunMode, SpotCampaignStatus


SUMMARY_PREFIX = "SPOT_CONTEXTLESS_AGENT_CHECKLIST "

BLIND_PROMPT = """You are in the local repository at c:\\coinbase. You have no prior session
context. Do not edit files. Task: determine how a spot order is created in
this project and explain, from the code/docs you find, the intended flow for a
spot BUY or SELL order, including which modules own planning/admission, wallet
checks, live placement, campaign/sweep paths, and safety/reconciliation. Do not
ask for guidance and do not rely on this prompt for architecture beyond the
task itself. Report: (1) where a new human/small agent should start reading,
(2) the canonical code path, (3) any confusing or missing context you found,
and (4) whether you would be confident creating a spot order correctly from
repo context alone."""

PASS_CRITERIA = [
    "README.spot-trading.md and docs/README.md are entry points",
    "spot uses the existing order lifecycle, not a spot-only placement engine",
    "direct/dashboard spot order admission goes through ActionConditionGuard",
    "stealth planning and reveal wallet checks include reveal-time recheck",
    "campaign/sweep paths are business/spot_portfolio_sweep.py, tools/run_spot_portfolio_sweep_live.py, business/spot_campaign.py, and tools/run_spot_campaign.py",
    "campaign tools do not submit Coinbase orders; live sweep requires --approved-live-orders",
    "wallet sellability is distinct from known profitable inventory",
    "client_order_id is internal tracking id; order_id is exchange evidence only",
    "reconciliation/fill-backfill compares local state against Coinbase reality",
    "planned skips are audit rows, not failed Coinbase submissions",
    "direct dashboard, stealth reveal, and portfolio sweep each have a submission/audit evidence path",
    "live USDC sweep placements use UUID client_order_id values and sweep-ledger/event payload identity",
    "direct dashboard and live sweep publish order_submitted/rest_submit evidence when available",
    "dashboard create_parent_order is local DB CRUD and does not submit Coinbase orders",
    "direct dashboard place_order is immediate manual placement and does not pre-insert order_parent",
    "Hotpoint Manager live placement is gated and spot is blocked unless explicitly enabled",
    "direct/stealth spot scope comes from products.json while sweep/campaign scope is USDC-only",
    "failed stealth REST placement records failed evidence without claiming a live revealed placement",
    "new spot order-creation surfaces must reuse or extend the canonical audit path",
]


def build_checklist(*, generated_at: datetime | None = None) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        "generated_at": timestamp.isoformat(),
        "mode": SpotCampaignRunMode.CONTEXTLESS_AGENT_CHECKLIST.value,
        "status": SpotCampaignStatus.RECORDED.value,
        "source_doc": "docs/SPOT_CONTEXTLESS_AGENT_TESTING.md",
        "blind_prompt": BLIND_PROMPT,
        "pass_criteria": PASS_CRITERIA,
        "evidence_template": {
            "date": timestamp.date().isoformat(),
            "agent_type": None,
            "prompt_version": "phase_181",
            "result": None,
            "missing_items": [],
            "docs_or_code_changed": [],
        },
        "failure_handling": [
            "fix repository docs or code instead of coaching the agent",
            "rerun the same blind prompt after the fix",
            "record result in docs/SPOT_CONTEXTLESS_AGENT_TESTING.md and the roadmap",
        ],
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "total_submitted_notional_usdc": "0",
        "total_executed_notional_usdc": "0",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the read-only contextless-agent spot checklist."
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit the full blind prompt and criterion text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checklist = build_checklist()
    if args.summary_only:
        checklist = dict(checklist)
        checklist.pop("blind_prompt", None)
        checklist["pass_criteria_count"] = len(PASS_CRITERIA)
        checklist.pop("pass_criteria", None)
    print(SUMMARY_PREFIX + json.dumps(checklist, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
