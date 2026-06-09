"""Run the public, read-only spot release gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.enums import SpotReleaseGateStatus

SUMMARY_PREFIX = "SPOT_RELEASE_GATE_SUMMARY "


@dataclass(frozen=True)
class GateStep:
    name: str
    command: tuple[str, ...]
    required: bool = True


def _run_step(step: GateStep) -> dict[str, Any]:
    completed = subprocess.run(
        step.command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return {
        "name": step.name,
        "required": step.required,
        "command": list(step.command),
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "tail": output[-4000:],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run read-only spot release checks without live Coinbase orders."
    )
    parser.add_argument(
        "--include-browser",
        action="store_true",
        help="Also run the Playwright dashboard smoke gate.",
    )
    parser.add_argument(
        "--include-coinbase-readonly",
        action="store_true",
        help="Also run read-only Coinbase-backed sweep status/P&L checks.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("runtime_state") / "spot_portfolio_sweeps.jsonl",
        help="Sweep state ledger for read-only status checks.",
    )
    parser.add_argument(
        "--campaign-config-file",
        type=Path,
        default=None,
        help="Optional spot campaign config to validate with the campaign release gate.",
    )
    parser.add_argument(
        "--campaign-state-file",
        type=Path,
        default=Path("runtime_state") / "spot_campaigns.jsonl",
        help="Campaign state ledger used by optional campaign release checks.",
    )
    return parser


def build_release_gate_steps(
    *,
    args: argparse.Namespace,
    python: str,
) -> list[GateStep]:
    steps = [
        GateStep(
            name="focused_spot_readiness_regression",
            command=(python, "tools/run_spot_readiness_regression.py"),
        ),
    ]
    if args.include_browser:
        steps.append(
            GateStep(
                name="spot_readiness_browser_smoke",
                command=(python, "tools/run_spot_readiness_browser_smoke.py"),
            )
        )
    if args.include_coinbase_readonly:
        steps.extend([
            GateStep(
                name="spot_sweep_operator_status",
                command=(
                    python,
                    "tools/run_spot_portfolio_sweep_live.py",
                    "--status",
                    "--state-file",
                    str(args.state_file),
                ),
            ),
            GateStep(
                name="spot_sweep_pnl_report",
                command=(
                    python,
                    "tools/run_spot_portfolio_sweep_live.py",
                    "--pnl-report",
                    "--summary-only",
                    "--state-file",
                    str(args.state_file),
                ),
            ),
            GateStep(
                name="spot_cost_basis_inventory_coverage",
                command=(
                    python,
                    "tools/run_spot_portfolio_sweep_live.py",
                    "--inventory-coverage",
                    "--include-coinbase-average-cost",
                    "--summary-only",
                    "--state-file",
                    str(args.state_file),
                ),
            ),
            GateStep(
                name="spot_cost_basis_drift_audit",
                command=(
                    python,
                    "tools/run_spot_portfolio_sweep_live.py",
                    "--cost-basis-drift-audit",
                    "--summary-only",
                    "--state-file",
                    str(args.state_file),
                ),
            ),
        ])
    if args.campaign_config_file is not None:
        steps.append(
            GateStep(
                name="spot_campaign_release_gate",
                command=(
                    python,
                    "tools/run_spot_campaign.py",
                    "--config-file",
                    str(args.campaign_config_file),
                    "--release-gate",
                    "--summary-only",
                    "--state-file",
                    str(args.campaign_state_file),
                    "--sweep-state-file",
                    str(args.state_file),
                ),
            )
        )
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    python = sys.executable
    steps = build_release_gate_steps(args=args, python=python)

    results = [_run_step(step) for step in steps]
    passed = all(result["passed"] or not result["required"] for result in results)
    summary = {
        "status": (
            SpotReleaseGateStatus.PASSED.value
            if passed
            else SpotReleaseGateStatus.FAILED.value
        ),
        "live_coinbase_orders_ran": False,
        "live_order_notional_usdc": "0",
        "step_count": len(results),
        "steps": results,
    }
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
