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
spot BUY or SELL order, including which modules own Admin API admission, wallet
checks, Controlled-live placement/cancel, source-disabled compatibility paths,
campaign/sweep reporting, and safety/reconciliation. Do not
ask for guidance and do not rely on this prompt for architecture beyond the
task itself. Report: (1) where a new human/small agent should start reading,
(2) the canonical code path, (3) any confusing or missing context you found,
and (4) whether you would be confident creating a spot order correctly from
repo context alone."""

PASS_CRITERIA = [
    "README.spot-trading.md and docs/README.md are entry points",
    "spot uses the existing order lifecycle, not a spot-only placement engine",
    "six installed Controlled-live mutation routes: manual root place/cancel and explicit attached-intent materialization/exact-child safe-closeout plus operator Hotpoint run-once/exact-child safe-closeout",
    "intent attachment is local-only and never supplies materialization authority; materialization and safe-closeout each require fresh separate explicit operator acknowledgement",
    "exact outer authority, manager lease, current service decision, RBAC, intent, idempotency, approval, caps, Test portfolio/wallet, audit, reconciliation, and final route scope are backend gates",
    "the browser forwards requests and readback without Coinbase credentials or execution authority",
    "campaign/sweep paths are business/spot_portfolio_sweep.py, tools/run_spot_portfolio_sweep_live.py, business/spot_campaign.py, and tools/run_spot_campaign.py",
    "campaign/sweep mutation modes are source-disabled and --approved-live-orders grants no authority",
    "dashboard place/cancel/hotpoint and legacy main.py Controlled-live startup are source-disabled",
    "wallet sellability is distinct from known profitable inventory",
    "client_order_id is internal tracking id; order_id is exchange evidence only",
    "reconciliation/fill-backfill compares local state against Coinbase reality",
    "planned skips are audit rows, not failed Coinbase submissions",
    "supported Admin API manual-root, attached-intent, and operator Hotpoint mutation routes have durable submission, linkage, audit, and terminal readback evidence",
    "direct-order audit separates read-only audit command fields from audited-order submission/fill evidence fields",
    "dashboard create_parent_order is local DB CRUD and does not submit Coinbase orders",
    "dashboard exchange mutation messages return fixed source-disabled responses before runtime lookup",
    "new Spot order-creation surfaces cannot bypass authenticated Admin API admission or mint a parallel execution scope",
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
